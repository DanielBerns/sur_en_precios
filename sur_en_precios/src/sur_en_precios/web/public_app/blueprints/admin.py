"""Admin Blueprint for user management, basket audit, and daily database updates."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    session,
    url_for,
)
from flask_babel import gettext as _
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sur_en_precios.domain.models_public import Article, DailyPrice, PointOfSale
from sur_en_precios.web.control_app.app import ControlBase, ScraperLogModel
from sur_en_precios.web.public_app.catalog_slots import (
    VALID_SLOTS,
    get_slots_diagnostics,
    rollback_slot,
)
from sur_en_precios.web.public_app.database import (
    ensure_public_session_factory,
    get_catalog_repository,
    get_public_session,
    get_user_repository,
    get_user_session,
)
from sur_en_precios.web.public_app.maintenance import (
    clear_maintenance_mode,
    is_maintenance_mode,
)
from sur_en_precios.web.public_app.security import admin_required

logger = logging.getLogger("sur_en_precios.public_app.admin")

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _get_catalog_stats() -> Dict[str, Any]:
    """Retrieves high-level summary metrics from the active public catalog slot."""
    try:
        with get_public_session() as p_session:
            articles_count = (
                p_session.execute(select(func.count(Article.id))).scalar() or 0
            )
            pos_count = (
                p_session.execute(select(func.count(PointOfSale.id))).scalar() or 0
            )
            prices_count = (
                p_session.execute(select(func.count()).select_from(DailyPrice)).scalar()
                or 0
            )

            latest_date = p_session.execute(select(func.max(DailyPrice.date))).scalar()

            return {
                "articles_count": articles_count,
                "pos_count": pos_count,
                "prices_count": prices_count,
                "latest_date": latest_date.strftime("%Y-%m-%d")
                if latest_date
                else "Sin datos",
            }
    except Exception as exc:
        logger.error("Failed to query catalog stats: %s", exc)
        return {
            "articles_count": 0,
            "pos_count": 0,
            "prices_count": 0,
            "latest_date": "Error",
        }


def _get_scraper_logs(limit: int = 10) -> List[Any]:
    """Retrieves recent logs from control.sqlite."""
    try:
        config = current_app.config.get("APP_CONFIG")

        if not config:
            return []
        control_path = config.get_control_db_path()
        from sqlalchemy import create_engine

        ctrl_engine = create_engine(f"sqlite:///{control_path}")
        ControlBase.metadata.create_all(ctrl_engine)
        with Session(ctrl_engine) as ctrl_session:
            stmt = (
                select(ScraperLogModel).order_by(ScraperLogModel.id.desc()).limit(limit)
            )
            return list(ctrl_session.execute(stmt).scalars().all())
    except Exception as exc:
        logger.error("Failed to fetch scraper logs: %s", exc)
        return []


@admin_bp.route("")
@admin_bp.route("/dashboard")
@admin_required
def dashboard():
    """Admin dashboard overview."""
    with get_user_session() as u_session:
        user_repo = get_user_repository(u_session)
        users = user_repo.get_all_users()
        baskets = user_repo.get_all_baskets()

    catalog_stats = _get_catalog_stats()

    public_baskets_cnt = sum(1 for b in baskets if b.is_public)
    private_baskets_cnt = len(baskets) - public_baskets_cnt

    return render_template(
        "admin/dashboard.html",
        users_count=len(users),
        baskets_count=len(baskets),
        public_baskets_count=public_baskets_cnt,
        private_baskets_count=private_baskets_cnt,
        catalog_stats=catalog_stats,
    )


@admin_bp.route("/users")
@admin_required
def users():
    """Lists all registered users."""
    with get_user_session() as u_session:
        user_repo = get_user_repository(u_session)
        all_users = user_repo.get_all_users()

    return render_template("admin/users.html", users=all_users)


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id: int):
    """Deletes a user and cascades to all their private baskets."""
    current_admin_id = session.get("user_id")
    if user_id == current_admin_id:
        flash(_("No puedes eliminar tu propia cuenta de administrador."), "error")
        return redirect(url_for("admin.users"))

    with get_user_session() as u_session:
        user_repo = get_user_repository(u_session)
        target = user_repo.get_user_by_id(user_id)
        if not target:
            flash(_("El usuario no existe."), "error")
            return redirect(url_for("admin.users"))

        target_name = target.username
        user_repo.delete_user(user_id)

    flash(
        _(
            "El usuario '%(name)s' y todas sus canastas fueron eliminados con éxito.",
            name=target_name,
        ),
        "success",
    )
    return redirect(url_for("admin.users"))


@admin_bp.route("/baskets")
@admin_required
def all_baskets():
    """Lists all baskets across all users (both public and private)."""
    with get_user_session() as u_session:
        user_repo = get_user_repository(u_session)
        all_b_list = user_repo.get_all_baskets()

    return render_template("admin/baskets.html", baskets=all_b_list)


@admin_bp.route("/baskets/<uuid_str>")
@admin_required
def basket_detail(uuid_str: str):
    """Admin inspects any basket (public or private)."""
    with get_user_session() as u_session:
        user_repo = get_user_repository(u_session)
        basket_entity = user_repo.get_basket_by_uuid(uuid_str)

    if not basket_entity:
        flash(_("La canasta solicitada no existe."), "error")
        return redirect(url_for("admin.baskets"))

    items_data = []
    with get_public_session() as p_session:
        cat_repo = get_catalog_repository(p_session)
        for it in basket_entity.items:
            art = cat_repo.get_article_by_ean(it.ean)
            items_data.append(
                {
                    "item": it,
                    "article": art,
                }
            )

    return render_template(
        "admin/basket_detail.html",
        basket=basket_entity,
        items_data=items_data,
    )


def _format_bytes(size_bytes: int) -> str:
    size_mb = size_bytes / (1024 * 1024)
    return f"{size_mb:.2f} MB" if size_mb >= 1.0 else f"{size_bytes / 1024:.1f} KB"


@admin_bp.route("/system", methods=["GET"])
@admin_required
def system() -> Any:
    """Displays Red/Green catalog database statistics and UNPSJB synchronization diagnostics."""
    config = current_app.config.get("APP_CONFIG")

    catalog_stats = _get_catalog_stats()
    recent_logs = _get_scraper_logs(limit=15)

    db_file_info: Dict[str, Any] = {
        "path": "",
        "filename": "public.sqlite",
        "exists": False,
        "size_formatted": "-",
        "mtime_formatted": "-",
        "active_slot": None,
        "standby_slot": None,
        "rollback_available": False,
        "db_sha256": "",
        "sqlite_mode": "Rollback Journal (DELETE)",
    }
    if config:
        diag = get_slots_diagnostics(config)
        active_db_path = diag["active_path"]
        active_slot = diag["active_slot"]
        db_file_info["path"] = str(active_db_path)
        db_file_info["filename"] = active_db_path.name
        db_file_info["active_slot"] = active_slot
        db_file_info["standby_slot"] = diag["standby_slot"]
        db_file_info["rollback_available"] = diag["rollback_available"]
        if active_slot in VALID_SLOTS:
            db_file_info["sqlite_mode"] = "Read-Only Immutable (Red/Green)"
            db_file_info["db_sha256"] = diag["slots"][active_slot].get("db_sha256", "")

        if active_db_path.exists() and active_db_path.stat().st_size > 0:
            db_file_info["exists"] = True
            stat = active_db_path.stat()
            db_file_info["size_formatted"] = _format_bytes(stat.st_size)
            mtime_dt = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            db_file_info["mtime_formatted"] = mtime_dt.strftime("%Y-%m-%d %H:%M:%S UTC")

    is_maintenance = is_maintenance_mode(config) if config else False
    sync_settings = config.get_sync_settings() if config else None

    return render_template(
        "admin/system.html",
        catalog_stats=catalog_stats,
        recent_logs=recent_logs,
        db_file_info=db_file_info,
        workdir=str(config.workdir) if config else "~/Info/sur_en_precios",
        is_maintenance=is_maintenance,
        sync_settings=sync_settings,
    )


@admin_bp.route("/system/rollback", methods=["POST"])
@admin_required
def system_rollback() -> Any:
    """Admin action reverting the active catalog slot to the validated standby slot."""
    config = current_app.config.get("APP_CONFIG")
    if not config:
        flash(_("Configuración de servidor no disponible."), "error")
        return redirect(url_for("admin.system"))

    try:
        new_state = rollback_slot(config)
        ensure_public_session_factory(current_app)
        clear_maintenance_mode(config)
        flash(
            _(
                "Catálogo revertido exitosamente al slot '%(slot)s'.",
                slot=(new_state.active_slot or "").upper(),
            ),
            "success",
        )
    except Exception as exc:
        logger.warning("Admin rollback failed: %s", exc)
        flash(
            _("No se pudo revertir el slot del catálogo: %(err)s", err=str(exc)),
            "error",
        )

    return redirect(url_for("admin.system"))
