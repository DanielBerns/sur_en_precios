"""Standalone local-network Flask application for visual editing of the style.css color palette."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    send_from_directory,
)
from werkzeug.middleware.dispatcher import DispatcherMiddleware

from sur_en_precios.config import read_config
from sur_en_precios.web.style_editor.preset_service import (
    DEFAULT_BUILTIN_PALETTES_DIR,
    delete_user_preset,
    list_presets,
    save_user_preset,
)
from sur_en_precios.web.style_editor.preview_env import build_preview_public_app
from sur_en_precios.web.style_editor.token_service import (
    CONTRAST_PAIRS,
    DEFAULT_STYLE_CSS_PATH,
    PaletteValidationError,
    apply_palette_to_css_text,
    evaluate_palette_contrast,
    parse_style_css_palette,
    save_palette_to_style_css,
    validate_palette_values,
)

logger = logging.getLogger(__name__)

__all__ = [
    "create_style_editor_app",
]


def create_style_editor_app(
    workdir: Path | None = None,
    style_css_path: Path | None = None,
    builtin_palettes_dir: Path | None = None,
) -> Flask:
    """Factory creating the standalone local-network visual style.css color palette editor."""
    config = read_config(workdir_override=workdir, should_create_override=True)
    target_css_path = (
        Path(style_css_path).expanduser().resolve()
        if style_css_path is not None
        else DEFAULT_STYLE_CSS_PATH
    )
    resolved_builtin_dir = (
        Path(builtin_palettes_dir).expanduser().resolve()
        if builtin_palettes_dir is not None
        else DEFAULT_BUILTIN_PALETTES_DIR
    )
    user_palettes_dir = (config.data_dir / "palettes").resolve()
    backup_dir = (user_palettes_dir / "backups").resolve()
    user_palettes_dir.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)

    editor_root = Path(__file__).resolve().parent
    templates_dir = editor_root / "templates"
    editor_static_dir = editor_root / "static"
    public_static_dir = editor_root.parent / "public_app" / "static"

    app = Flask(
        __name__,
        template_folder=str(templates_dir),
        static_folder=None,
    )
    app.config["APP_CONFIG"] = config
    app.config["STYLE_CSS_PATH"] = target_css_path
    app.config["USER_PALETTES_DIR"] = user_palettes_dir
    app.config["BACKUP_PALETTES_DIR"] = backup_dir
    app.config["BUILTIN_PALETTES_DIR"] = resolved_builtin_dir

    preview_env = build_preview_public_app(
        workdir=config.workdir,
        style_css_path=target_css_path,
    )
    app.config["PREVIEW_ENV"] = preview_env

    @app.after_request
    def _set_headers(response: Response) -> Response:
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.route("/editor-static/<path:filename>")
    def editor_static(filename: str) -> Response:
        """Serves the visual editor's own isolated CSS and JS files."""
        return send_from_directory(str(editor_static_dir), filename)

    @app.route("/static/css/style.css")
    def serve_target_style_css() -> Response:
        """Serves the target style.css being edited with no-store cache headers."""
        css_bytes = target_css_path.read_bytes()
        return Response(
            css_bytes,
            status=200,
            mimetype="text/css",
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    @app.route("/static/<path:filename>")
    def serve_shared_static(filename: str) -> Response:
        """Serves shared static assets (SVGs, images, favicons) from public_app/static."""
        return send_from_directory(str(public_static_dir), filename)

    @app.route("/")
    def index() -> str:
        """Renders the main split-screen visual color palette editor workspace."""
        palette = parse_style_css_palette(target_css_path)
        expected_names = set(palette.values.keys())
        presets = list_presets(
            expected_token_names=expected_names,
            user_palettes_dir=user_palettes_dir,
            builtin_palettes_dir=resolved_builtin_dir,
        )
        preview_routes = preview_env.get_preview_routes()
        initial_payload = {
            "palette": palette.to_dict(),
            "presets": [p.to_dict() for p in presets],
            "contrast_pairs": CONTRAST_PAIRS,
        }
        return render_template(
            "editor.html",
            palette=palette,
            presets=presets,
            preview_routes=preview_routes,
            initial_payload=initial_payload,
        )

    @app.route("/preview/kitchen-sink")
    def kitchen_sink() -> str:
        """Renders the comprehensive single-page UI component showcase."""
        return render_template("kitchen_sink.html")

    @app.route("/api/palette", methods=["GET"])
    def api_get_palette() -> tuple[Response, int]:
        """Returns the current parsed palette state and WCAG contrast analysis from style.css."""
        try:
            palette = parse_style_css_palette(target_css_path)
            return (
                jsonify(
                    {
                        "palette": palette.to_dict(),
                        "contrast_pairs": CONTRAST_PAIRS,
                    }
                ),
                200,
            )
        except Exception as exc:
            logger.exception("Failed to parse style.css palette: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/palette/validate", methods=["POST"])
    def api_validate_palette() -> tuple[Response, int]:
        """Validates candidate token hex values and computes WCAG contrast ratios."""
        try:
            payload: dict[str, Any] = request.get_json(force=True) or {}
            current_state = parse_style_css_palette(target_css_path)
            expected_names = set(current_state.values.keys())
            raw_tokens = payload.get("tokens")
            if not isinstance(raw_tokens, dict):
                raise PaletteValidationError("Request body must include a 'tokens' mapping.")

            normalized, resolved_scheme = validate_palette_values(
                raw_tokens,
                expected_names,
                color_scheme=payload.get("color_scheme"),
            )
            checks = [c.to_dict() for c in evaluate_palette_contrast(normalized)]
            return (
                jsonify(
                    {
                        "valid": True,
                        "color_scheme": resolved_scheme,
                        "tokens": normalized,
                        "contrast_checks": checks,
                    }
                ),
                200,
            )
        except PaletteValidationError as exc:
            return jsonify({"valid": False, "error": str(exc)}), 400
        except Exception as exc:
            logger.exception("Unexpected error validating palette: %s", exc)
            return jsonify({"valid": False, "error": str(exc)}), 500

    @app.route("/api/palette/save-css", methods=["POST"])
    def api_save_palette_css() -> tuple[Response, int]:
        """Validates and writes the updated 41 base color tokens directly into style.css on disk."""
        try:
            payload: dict[str, Any] = request.get_json(force=True) or {}
            raw_tokens = payload.get("tokens")
            if not isinstance(raw_tokens, dict):
                raise PaletteValidationError("Request body must include a 'tokens' mapping.")

            updated_state = save_palette_to_style_css(
                values=raw_tokens,
                style_css_path=target_css_path,
                color_scheme=payload.get("color_scheme"),
                backup_dir=backup_dir,
            )
            return (
                jsonify(
                    {
                        "status": "saved",
                        "palette": updated_state.to_dict(),
                    }
                ),
                200,
            )
        except PaletteValidationError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            logger.exception("Failed to save palette to style.css: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/palette/parse-import", methods=["POST"])
    def api_parse_import() -> tuple[Response, int]:
        """Parses and validates an imported YAML or JSON palette string."""
        try:
            payload: dict[str, Any] = request.get_json(force=True) or {}
            content = str(payload.get("content") or "").strip()
            if not content:
                raise PaletteValidationError("El contenido a importar está vacío.")

            try:
                parsed = yaml.safe_load(content)
            except Exception as exc:
                raise PaletteValidationError(
                    f"No se pudo interpretar el archivo YAML/JSON: {exc}"
                ) from exc

            if not isinstance(parsed, dict):
                raise PaletteValidationError(
                    "El contenido importado debe ser un objeto YAML o JSON con pares token: #rrggbb."
                )

            current_state = parse_style_css_palette(target_css_path)
            expected_names = set(current_state.values.keys())

            nested_tokens = parsed.get("tokens")
            raw_tokens: dict[str, Any] = (
                nested_tokens if isinstance(nested_tokens, dict) else parsed
            )
            merged_tokens = dict(current_state.values)
            for k, v in raw_tokens.items():
                if isinstance(k, str) and k.startswith("--color-"):
                    merged_tokens[k] = v

            scheme_hint = parsed.get("color_scheme") if isinstance(parsed.get("color_scheme"), str) else None
            normalized, resolved_scheme = validate_palette_values(
                merged_tokens,
                expected_names,
                color_scheme=scheme_hint,
            )
            checks = [c.to_dict() for c in evaluate_palette_contrast(normalized)]
            return (
                jsonify(
                    {
                        "tokens": normalized,
                        "color_scheme": resolved_scheme,
                        "contrast_checks": checks,
                    }
                ),
                200,
            )
        except PaletteValidationError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            logger.exception("Failed to import palette: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/presets", methods=["GET"])
    def api_list_presets() -> tuple[Response, int]:
        """Lists all built-in and user-saved palette presets."""
        try:
            current_state = parse_style_css_palette(target_css_path)
            presets = list_presets(
                expected_token_names=set(current_state.values.keys()),
                user_palettes_dir=user_palettes_dir,
                builtin_palettes_dir=resolved_builtin_dir,
            )
            return jsonify({"presets": [p.to_dict() for p in presets]}), 200
        except Exception as exc:
            logger.exception("Error listing palette presets: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/presets", methods=["POST"])
    def api_save_preset() -> tuple[Response, int]:
        """Saves a custom user palette preset in workdir/data/palettes/."""
        try:
            payload: dict[str, Any] = request.get_json(force=True) or {}
            name = str(payload.get("name") or "").strip()
            description = str(payload.get("description") or "").strip()
            raw_tokens = payload.get("tokens")
            if not isinstance(raw_tokens, dict):
                raise PaletteValidationError("Request body must include a 'tokens' mapping.")

            current_state = parse_style_css_palette(target_css_path)
            preset = save_user_preset(
                name=name,
                tokens=raw_tokens,
                expected_token_names=set(current_state.values.keys()),
                user_palettes_dir=user_palettes_dir,
                description=description,
                color_scheme=payload.get("color_scheme"),
                builtin_palettes_dir=resolved_builtin_dir,
            )
            return jsonify({"preset": preset.to_dict()}), 201
        except PaletteValidationError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            logger.exception("Failed to save user preset: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/presets/<slug>", methods=["DELETE"])
    def api_delete_preset(slug: str) -> tuple[Response, int]:
        """Deletes a user-defined palette preset by slug."""
        try:
            deleted = delete_user_preset(slug=slug, user_palettes_dir=user_palettes_dir)
            if not deleted:
                return jsonify({"error": f"Preset personalizado '{slug}' no encontrado."}), 404
            return jsonify({"status": "deleted", "slug": slug}), 200
        except PaletteValidationError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            logger.exception("Failed to delete user preset '%s': %s", slug, exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/export/style.css", methods=["GET", "POST"])
    def api_export_style_css() -> Response | tuple[Response, int]:
        """Generates a downloadable style.css file with the requested or current token values."""
        try:
            original_css = target_css_path.read_text(encoding="utf-8")
            if request.method == "POST":
                payload: dict[str, Any] = request.get_json(force=True) or {}
                raw_tokens = payload.get("tokens")
                if not isinstance(raw_tokens, dict):
                    raise PaletteValidationError("Request body must include a 'tokens' mapping.")
                output_css = apply_palette_to_css_text(
                    original_css,
                    raw_tokens,
                    color_scheme=payload.get("color_scheme"),
                )
            else:
                output_css = original_css

            return Response(
                output_css,
                status=200,
                mimetype="text/css",
                headers={
                    "Content-Disposition": 'attachment; filename="style.css"',
                    "Cache-Control": "no-store",
                },
            )
        except PaletteValidationError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            logger.exception("Failed to export style.css: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/export/palette.yaml", methods=["POST"])
    def api_export_palette_yaml() -> Response | tuple[Response, int]:
        """Generates a downloadable YAML palette file from the posted token values."""
        try:
            payload: dict[str, Any] = request.get_json(force=True) or {}
            raw_tokens = payload.get("tokens")
            if not isinstance(raw_tokens, dict):
                raise PaletteValidationError("Request body must include a 'tokens' mapping.")

            current_state = parse_style_css_palette(target_css_path)
            normalized, resolved_scheme = validate_palette_values(
                raw_tokens,
                set(current_state.values.keys()),
                color_scheme=payload.get("color_scheme"),
            )
            yaml_text = yaml.safe_dump(
                {
                    "name": "Paleta Exportada Sur en Precios",
                    "color_scheme": resolved_scheme,
                    "tokens": normalized,
                },
                sort_keys=False,
                allow_unicode=True,
            )
            return Response(
                yaml_text,
                status=200,
                mimetype="application/x-yaml",
                headers={
                    "Content-Disposition": 'attachment; filename="paleta_sur_en_precios.yaml"',
                    "Cache-Control": "no-store",
                },
            )
        except PaletteValidationError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            logger.exception("Failed to export palette YAML: %s", exc)
            return jsonify({"error": str(exc)}), 500

    # Mount the same-origin preview public_app under /preview/app
    app.wsgi_app = DispatcherMiddleware(  # type: ignore[method-assign]
        app.wsgi_app,
        {"/preview/app": preview_env.app.wsgi_app},
    )

    return app
