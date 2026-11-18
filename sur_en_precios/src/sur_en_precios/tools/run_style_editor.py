"""CLI entrypoint to launch the standalone local-network visual editor for style.css."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sur_en_precios.web.style_editor.app import create_style_editor_app
from sur_en_precios.web.style_editor.token_service import DEFAULT_STYLE_CSS_PATH

logger = logging.getLogger(__name__)

__all__ = [
    "build_parser",
    "main",
]


def build_parser() -> argparse.ArgumentParser:
    """Builds the CLI argument parser for the visual style.css color palette editor."""
    parser = argparse.ArgumentParser(
        description="Launch the local-network visual color palette editor for style.css."
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host interface to bind on the local network (default: 0.0.0.0).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5002,
        help="TCP port for the visual style editor server (default: 5002).",
    )
    parser.add_argument(
        "--workdir",
        "-w",
        help="Path to Sur en Precios working directory (defaults to WORKING_DIRECTORY or ~/Info/sur_en_precios).",
    )
    parser.add_argument(
        "--style-css",
        help=f"Path to target style.css file (default: {DEFAULT_STYLE_CSS_PATH}).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable Flask debug mode.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint for sur_en_precios.tools.run_style_editor."""
    parser = build_parser()
    args = parser.parse_args(argv)

    workdir_path = (
        Path(args.workdir).expanduser().resolve() if args.workdir else None
    )
    style_css_path = (
        Path(args.style_css).expanduser().resolve()
        if args.style_css
        else DEFAULT_STYLE_CSS_PATH
    )

    try:
        app = create_style_editor_app(
            workdir=workdir_path,
            style_css_path=style_css_path,
        )
        logger.info(
            "Starting Sur en Precios Visual Style Editor on http://%s:%d (target=%s)",
            args.host,
            args.port,
            style_css_path,
        )
        app.run(host=args.host, port=args.port, debug=bool(args.debug))
    except Exception as exc:
        logger.exception("Visual Style Editor failed to start: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
