import json
import logging
import re
from datetime import date
from typing import Dict, List

from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_babel import gettext as _

from sur_en_precios.domain.models_public import ArticleCard
from sur_en_precios.domain.models_user import Basket, BasketItem
from sur_en_precios.domain.services import (
    BasketPriceReportService,
    BasketYamlService,
    YamlValidationError,
)
from sur_en_precios.use_cases.optimize_basket import OptimizeBasketUseCase
from sur_en_precios.web.public_app.database import (
    get_catalog_repository,
    get_or_create_demo_user,
    get_price_repository,
    get_public_session,
    get_user_repository,
    get_user_session,
)
from sur_en_precios.web.public_app.schemas import (
    BasketCreateForm,
    BasketSaveForm,
)
from sur_en_precios.web.public_app.security import login_required

logger = logging.getLogger("sur_en_precios.public_app.baskets")

baskets_bp = Blueprint("baskets", __name__, url_prefix="/baskets")


def _resolve_user_id(user_repo) -> int:
    """Returns authenticated user_id, or test demo_user if in test mode."""
    uid = session.get("user_id")
    if uid:
        return int(uid)
    if current_app.config.get("TESTING"):
        return int(get_or_create_demo_user(user_repo).id)
    raise PermissionError("User not authenticated")


@baskets_bp.route("", strict_slashes=False)
@login_required
def baskets():
    """Lists current authenticated user's baskets."""
    try:
        with get_user_session() as u_session:
            user_repo = get_user_repository(u_session)
            user_id = _resolve_user_id(user_repo)
            shopping_lists = user_repo.get_user_baskets(user_id=user_id)
            return render_template(
                "baskets/baskets.html", shopping_lists=shopping_lists
            )
    except Exception as exc:
        logger.error("Error loading baskets: %s", exc)
        flash(_("Error al cargar las canastas."), "error")
        return render_template("baskets/baskets.html", shopping_lists=[])


@baskets_bp.route("/new")
@login_required
def new_basket():
    """Creates a new empty draft basket for current user."""
    try:
        with get_user_session() as u_session:
            user_repo = get_user_repository(u_session)
            user_id = _resolve_user_id(user_repo)
            draft = Basket(
                user_id=user_id,
                name=_("Nueva Canasta"),
                is_public=False,
                items=[],
            )
            saved = user_repo.save_basket(draft)
            return redirect(url_for("baskets.edit_basket", basket_id=saved.id))
    except Exception as exc:
        logger.error("Error creating new basket: %s", exc)
        flash(_("Error al crear una nueva canasta."), "error")
        return redirect(url_for("baskets.baskets"))


@baskets_bp.route("/create", methods=["POST"])
@login_required
def create_basket():
    """Creates a basket from quick barcode form."""
    try:
        form = BasketCreateForm(
            name=request.form.get("name", "Canasta de Compras"),
            eans=request.form.get("eans", ""),
        )

        with get_user_session() as u_session:
            user_repo = get_user_repository(u_session)
            user_id = _resolve_user_id(user_repo)

            items = [
                BasketItem(
                    ean=ean, quantity=1, selected=True, numerator=1, denominator=1
                )
                for ean in form.ean_list
            ]
            new_basket = Basket(
                id=None,
                user_id=user_id,
                name=form.name,
                items=items,
                is_public=False,
            )
            saved = user_repo.save_basket(new_basket)
            return redirect(url_for("baskets.edit_basket", basket_id=saved.id))
    except Exception as exc:
        logger.error("Error creating basket from form: %s", exc)
        flash(_("Error al guardar la canasta."), "error")
        return redirect(url_for("baskets.baskets"))


@baskets_bp.route("/<int:basket_id>/edit")
@login_required
def edit_basket(basket_id: int):
    """Edits a basket owned by the user or viewed by admin."""
    try:
        with get_user_session() as user_session:
            user_repo = get_user_repository(user_session)
            user_id = _resolve_user_id(user_repo)
            is_admin = session.get("is_admin")

            if is_admin:
                all_b = user_repo.get_all_baskets()
                basket = next((b for b in all_b if b.id == basket_id), None)
            else:
                user_baskets = user_repo.get_user_baskets(user_id=user_id)
                basket = next((b for b in user_baskets if b.id == basket_id), None)

            if not basket:
                flash(
                    _("Canasta no encontrada o no tienes permisos para acceder."),
                    "error",
                )
                return redirect(url_for("baskets.baskets"))

            with get_public_session() as pub_session:
                cat_repo = get_catalog_repository(pub_session)
                departments = cat_repo.get_departments()
                departments_data = [
                    {
                        "name": d.name,
                        "slug": d.slug,
                        "children": [
                            {"name": c.name, "slug": c.slug} for c in (d.children or [])
                        ],
                    }
                    for d in departments
                ]
                items_data = []
                eans_list = []
                for item in basket.items:
                    eans_list.append(item.ean)
                    card = cat_repo.get_article_by_ean(item.ean)
                    items_data.append(
                        {
                            "ean": item.ean,
                            "name": card.name if card else f"Producto {item.ean}",
                            "brand": getattr(card, "brand_name", "") if card else "",
                            "category": getattr(card, "category_name", "")
                            if card
                            else "",
                            "quantity": item.quantity,
                            "selected": getattr(item, "selected", True) is not False,
                            "numerator": getattr(item, "numerator", 1) or 1,
                            "denominator": getattr(item, "denominator", 1) or 1,
                        }
                    )

            return render_template(
                "baskets/editor.html",
                basket=basket,
                items_data=items_data,
                eans_list=eans_list,
                eans_csv=",".join(eans_list),
                departments=departments_data,
                departments_json=json.dumps(departments_data),
            )
    except Exception as exc:
        logger.error("Error loading basket editor: %s", exc)
        flash(_("Ocurrió un error al cargar el editor de canasta."), "error")
        return redirect(url_for("baskets.baskets"))


@baskets_bp.route("/<int:basket_id>/save", methods=["POST"])
@login_required
def save_basket(basket_id: int):
    """Saves updates to a basket."""
    try:
        with get_user_session() as u_session:
            user_repo = get_user_repository(u_session)
            user_id = _resolve_user_id(user_repo)
            is_admin = session.get("is_admin")

            if is_admin:
                all_b = user_repo.get_all_baskets()
                basket = next((b for b in all_b if b.id == basket_id), None)
            else:
                user_baskets = user_repo.get_user_baskets(user_id=user_id)
                basket = next((b for b in user_baskets if b.id == basket_id), None)

            if not basket:
                flash(_("Canasta no encontrada."), "error")
                return redirect(url_for("baskets.baskets"))

            form = BasketSaveForm.from_form(
                request.form.to_dict(), default_name=basket.name
            )

            updated_items: List[BasketItem] = [
                BasketItem(
                    ean=it.ean,
                    quantity=it.quantity,
                    selected=it.selected,
                    numerator=it.numerator,
                    denominator=it.denominator,
                )
                for it in form.items
            ]

            basket.name = form.name
            basket.is_public = form.is_public
            basket.items = updated_items

            user_repo.save_basket(basket)
            if form.action == "optimize":
                return redirect(url_for("optimize.optimize", list_id=basket.id))

            flash(_("Canasta guardada exitosamente."), "success")
            return redirect(url_for("baskets.edit_basket", basket_id=basket.id))
    except Exception as exc:
        logger.error("Error saving basket %d: %s", basket_id, exc)
        flash(_("Error al guardar los cambios en la canasta."), "error")
        return redirect(url_for("baskets.edit_basket", basket_id=basket_id))


@baskets_bp.route("/<int:basket_id>/delete", methods=["POST"])
@login_required
def delete_basket(basket_id: int):
    """Deletes a basket owned by the user or by admin."""
    try:
        with get_user_session() as u_session:
            user_repo = get_user_repository(u_session)
            user_id = _resolve_user_id(user_repo)
            is_admin = session.get("is_admin")

            if is_admin:
                all_b = user_repo.get_all_baskets()
                basket = next((b for b in all_b if b.id == basket_id), None)
                if basket:
                    user_repo.delete_basket(basket_id, basket.user_id)
                    flash(_("Canasta eliminada por el administrador."), "success")
                    return redirect(url_for("baskets.baskets"))
            else:
                user_repo.delete_basket(basket_id, user_id)
                flash(_("Canasta eliminada."), "success")
    except Exception as exc:
        logger.error("Error deleting basket %d: %s", basket_id, exc)
        flash(_("Error al eliminar la canasta."), "error")
    return redirect(url_for("baskets.baskets"))


@baskets_bp.route("/<int:basket_id>/export")
@login_required
def export_basket(basket_id: int):
    """Exports personal basket as YAML."""
    try:
        with get_user_session() as u_session:
            user_repo = get_user_repository(u_session)
            user_id = _resolve_user_id(user_repo)
            is_admin = session.get("is_admin")

            if is_admin:
                all_b = user_repo.get_all_baskets()
                basket = next((b for b in all_b if b.id == basket_id), None)
            else:
                lists = user_repo.get_user_baskets(user_id=user_id)
                basket = next((b for b in lists if b.id == basket_id), None)

            if not basket:
                flash(_("Canasta no encontrada."), "error")
                return redirect(url_for("baskets.baskets"))

            with get_public_session() as p_session:
                cat_repo = get_catalog_repository(p_session)
                metadata: Dict[str, ArticleCard] = {}
                for item in basket.items:
                    card = cat_repo.get_article_by_ean(item.ean)
                    if card:
                        metadata[item.ean] = card

            yaml_str = BasketYamlService.export_to_yaml(
                basket, articles_metadata=metadata
            )
            filename = f"canasta_{basket_id}.yaml"
            return Response(
                yaml_str,
                mimetype="application/x-yaml",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
    except Exception as exc:
        logger.error("Error exporting basket %d: %s", basket_id, exc)
        flash(_("Error al exportar la canasta en formato YAML."), "error")
        return redirect(url_for("baskets.edit_basket", basket_id=basket_id))


@baskets_bp.route("/<int:basket_id>/export-prices-json")
@login_required
def export_basket_prices_json(basket_id: int):
    """Exports personal basket price report as JSON."""
    try:
        with get_user_session() as u_session:
            user_repo = get_user_repository(u_session)
            user_id = _resolve_user_id(user_repo)
            is_admin = session.get("is_admin")

            if is_admin:
                all_b = user_repo.get_all_baskets()
                basket = next((b for b in all_b if b.id == basket_id), None)
            else:
                lists = user_repo.get_user_baskets(user_id=user_id)
                basket = next((b for b in lists if b.id == basket_id), None)

            if not basket:
                flash(
                    _("Canasta no encontrada o no tienes permisos para acceder."),
                    "error",
                )
                return redirect(url_for("baskets.baskets"))

            config = current_app.config["APP_CONFIG"]
            with get_public_session() as pub_session:
                cat_repo = get_catalog_repository(pub_session)
                price_repo = get_price_repository(pub_session)

                region = config.get_region()
                cities = cat_repo.get_cities_for_region(region)

                latest_date = price_repo.get_latest_price_date()
                default_date_str = (
                    latest_date.strftime("%Y-%m-%d")
                    if latest_date
                    else date.today().strftime("%Y-%m-%d")
                )
                selected_date_str = request.args.get("date") or default_date_str
                try:
                    target_date = date.fromisoformat(selected_date_str)
                except ValueError:
                    target_date = latest_date or date.today()
                    selected_date_str = target_date.strftime("%Y-%m-%d")

                req_city = request.args.get("city")
                if req_city:
                    matching_city = next(
                        (c for c in cities if c.lower() == req_city.strip().lower()),
                        None,
                    )
                    selected_city = matching_city or req_city.strip()
                elif cities:
                    selected_city = next(
                        (c for c in cities if "comodoro" in c.lower()), cities[0]
                    )
                else:
                    selected_city = "General"

                active_items = [
                    it
                    for it in basket.items
                    if getattr(it, "selected", True) is not False
                ]

                use_case = OptimizeBasketUseCase(cat_repo, price_repo)
                result = use_case.execute(selected_city, target_date, active_items)

                requested_products = []
                for item in active_items:
                    art = cat_repo.get_article_by_ean(item.ean)
                    requested_products.append(
                        {
                            "ean": item.ean,
                            "name": (
                                getattr(art, "name", f"Producto {item.ean}")
                                if art
                                else f"Producto {item.ean}"
                            ),
                            "brand": (
                                getattr(art, "brand_name", "") if art else ""
                            ),
                        }
                    )

                priced_eans = {
                    opt.product.ean
                    for opt in (result.item_by_item_optimal or [])
                }
                unpriced_items = [
                    p for p in requested_products if p["ean"] not in priced_eans
                ]

                json_str = BasketPriceReportService.export_to_json(
                    result=result,
                    basket=basket,
                    unpriced_items=unpriced_items,
                )
                clean_city = re.sub(r"[^a-zA-Z0-9_\-]", "_", selected_city)
                clean_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", basket.name)
                filename = f"reporte_precios_{clean_name}_{clean_city}_{selected_date_str}.json"
                return Response(
                    json_str,
                    mimetype="application/json",
                    headers={
                        "Content-Disposition": f'attachment; filename="{filename}"'
                    },
                )
    except Exception as exc:
        logger.error("Error exporting basket prices JSON %d: %s", basket_id, exc)
        flash(_("Error al exportar el reporte de precios en formato JSON."), "error")
        return redirect(url_for("baskets.edit_basket", basket_id=basket_id))


@baskets_bp.route("/public/<uuid_str>/export")
def export_public_basket(uuid_str: str):
    """Exports a public basket as YAML without requiring login."""
    try:
        with get_user_session() as u_session:
            user_repo = get_user_repository(u_session)
            basket = user_repo.get_basket_by_uuid(uuid_str)
            if not basket or not basket.is_public:
                flash(_("Esta canasta es privada o no existe."), "error")
                return redirect(url_for("baskets.baskets")), 404

            with get_public_session() as p_session:
                cat_repo = get_catalog_repository(p_session)
                metadata: Dict[str, ArticleCard] = {}
                for item in basket.items:
                    card = cat_repo.get_article_by_ean(item.ean)
                    if card:
                        metadata[item.ean] = card

            yaml_str = BasketYamlService.export_to_yaml(
                basket, articles_metadata=metadata
            )
            filename = f"canasta_publica_{uuid_str[:8]}.yaml"
            return Response(
                yaml_str,
                mimetype="application/x-yaml",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
    except Exception as exc:
        logger.error("Error exporting public basket %s: %s", uuid_str, exc)
        flash(_("Error al exportar la canasta pública."), "error")
        return redirect(url_for("baskets.baskets"))


@baskets_bp.route("/public/<uuid_str>/export-prices-json")
def export_public_basket_prices_json(uuid_str: str):
    """Exports a public basket price report as JSON without requiring login."""
    try:
        user_id = session.get("user_id")
        is_admin = session.get("is_admin")

        with get_user_session() as u_session:
            user_repo = get_user_repository(u_session)
            basket = user_repo.get_basket_by_uuid(uuid_str)
            if not basket:
                flash(_("La canasta solicitada no existe."), "error")
                return redirect(url_for("baskets.baskets")), 404

            if (
                not basket.is_public
                and not is_admin
                and (not user_id or basket.user_id != user_id)
            ):
                flash(_("Esta canasta es privada o no existe."), "error")
                return redirect(url_for("baskets.baskets")), 404

            config = current_app.config["APP_CONFIG"]
            with get_public_session() as pub_session:
                cat_repo = get_catalog_repository(pub_session)
                price_repo = get_price_repository(pub_session)

                region = config.get_region()
                cities = cat_repo.get_cities_for_region(region)

                latest_date = price_repo.get_latest_price_date()
                default_date_str = (
                    latest_date.strftime("%Y-%m-%d")
                    if latest_date
                    else date.today().strftime("%Y-%m-%d")
                )
                selected_date_str = request.args.get("date") or default_date_str
                try:
                    target_date = date.fromisoformat(selected_date_str)
                except ValueError:
                    target_date = latest_date or date.today()
                    selected_date_str = target_date.strftime("%Y-%m-%d")

                req_city = request.args.get("city")
                if req_city:
                    matching_city = next(
                        (c for c in cities if c.lower() == req_city.strip().lower()),
                        None,
                    )
                    selected_city = matching_city or req_city.strip()
                elif cities:
                    selected_city = next(
                        (c for c in cities if "comodoro" in c.lower()), cities[0]
                    )
                else:
                    selected_city = "General"

                active_items = [
                    it
                    for it in basket.items
                    if getattr(it, "selected", True) is not False
                ]

                use_case = OptimizeBasketUseCase(cat_repo, price_repo)
                result = use_case.execute(selected_city, target_date, active_items)

                requested_products = []
                for item in active_items:
                    art = cat_repo.get_article_by_ean(item.ean)
                    requested_products.append(
                        {
                            "ean": item.ean,
                            "name": (
                                getattr(art, "name", f"Producto {item.ean}")
                                if art
                                else f"Producto {item.ean}"
                            ),
                            "brand": (
                                getattr(art, "brand_name", "") if art else ""
                            ),
                        }
                    )

                priced_eans = {
                    opt.product.ean
                    for opt in (result.item_by_item_optimal or [])
                }
                unpriced_items = [
                    p for p in requested_products if p["ean"] not in priced_eans
                ]

                json_str = BasketPriceReportService.export_to_json(
                    result=result,
                    basket=basket,
                    unpriced_items=unpriced_items,
                )
                clean_city = re.sub(r"[^a-zA-Z0-9_\-]", "_", selected_city)
                clean_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", basket.name)
                filename = f"reporte_precios_{clean_name}_{clean_city}_{selected_date_str}.json"
                return Response(
                    json_str,
                    mimetype="application/json",
                    headers={
                        "Content-Disposition": f'attachment; filename="{filename}"'
                    },
                )
    except Exception as exc:
        logger.error("Error exporting public basket prices JSON %s: %s", uuid_str, exc)
        flash(_("Error al exportar el reporte de precios de la canasta pública."), "error")
        return redirect(url_for("baskets.baskets"))


@baskets_bp.route("/import", methods=["POST"])
@login_required
def import_basket():
    """Imports basket from uploaded YAML file or pasted text."""
    try:
        content = ""
        if "yaml_file" in request.files:
            file = request.files["yaml_file"]
            if file and file.filename:
                if not (
                    file.filename.endswith(".yaml") or file.filename.endswith(".yml")
                ):
                    flash(
                        _("Formato de archivo inválido. Debe ser .yaml o .yml"),
                        "error",
                    )
                    return redirect(url_for("baskets.baskets"))
                content = file.read().decode("utf-8", errors="replace")

        if not content and "yaml_text" in request.form:
            content = request.form.get("yaml_text", "")

        if not content.strip():
            flash(_("No se proporcionó contenido YAML para importar."), "error")
            return redirect(url_for("baskets.baskets"))

        parsed = BasketYamlService.import_from_yaml(content)

        with get_user_session() as u_session:
            user_repo = get_user_repository(u_session)
            user_id = _resolve_user_id(user_repo)

            items = [
                BasketItem(
                    ean=it.ean,
                    quantity=it.quantity,
                    selected=it.selected,
                    numerator=it.numerator,
                    denominator=it.denominator,
                )
                for it in parsed.items
            ]
            new_basket = Basket(
                user_id=user_id,
                name=parsed.name,
                is_public=parsed.is_public,
                items=items,
            )
            saved = user_repo.save_basket(new_basket)

        for w in parsed.warnings:
            flash(w, "warning")
        flash(_("Canasta importada exitosamente."), "success")
        return redirect(url_for("baskets.edit_basket", basket_id=saved.id))

    except YamlValidationError as yerr:
        logger.warning("YAML validation failure on import: %s", yerr)
        flash(str(yerr), "error")
        return redirect(url_for("baskets.baskets"))
    except Exception as exc:
        logger.error("Unexpected error importing basket YAML: %s", exc)
        flash(_("Ocurrió un error inesperado al procesar el archivo YAML."), "error")
        return redirect(url_for("baskets.baskets"))


@baskets_bp.route("/open")
def open_public_by_uuid():
    """Redirects to public view for a given UUID query string."""
    uuid_str = request.args.get("uuid", "").strip()
    if not uuid_str:
        flash(_("Debes ingresar un código UUID válido."), "warning")
        return redirect(url_for("baskets.baskets"))
    return redirect(url_for("baskets.view_public_basket", uuid_str=uuid_str))


@baskets_bp.route("/public/<uuid_str>")
def view_public_basket(uuid_str: str):
    """Public view of a basket. Allows public access or owner/admin access."""
    try:
        user_id = session.get("user_id")
        is_admin = session.get("is_admin")

        with get_user_session() as u_session:
            user_repo = get_user_repository(u_session)
            basket = user_repo.get_basket_by_uuid(uuid_str)
            if not basket:
                flash(_("La canasta solicitada no existe."), "error")
                return render_template("baskets/not_available.html"), 404

            if (
                not basket.is_public
                and not is_admin
                and (not user_id or basket.user_id != user_id)
            ):
                flash(_("Esta canasta es privada."), "error")
                return render_template("baskets/not_available.html"), 404

            items_data = []
            with get_public_session() as pub_session:
                cat_repo = get_catalog_repository(pub_session)
                for item in basket.items:
                    card = cat_repo.get_article_by_ean(item.ean)
                    items_data.append(
                        {
                            "ean": item.ean,
                            "name": card.name if card else f"Producto {item.ean}",
                            "brand": getattr(card, "brand_name", "") if card else "",
                            "category": getattr(card, "category_name", "")
                            if card
                            else "",
                            "quantity": item.quantity,
                            "selected": getattr(item, "selected", True),
                            "numerator": getattr(item, "numerator", 1) or 1,
                            "denominator": getattr(item, "denominator", 1) or 1,
                        }
                    )

            return render_template(
                "baskets/public_view.html",
                basket=basket,
                items_data=items_data,
            )
    except Exception as exc:
        logger.error("Error viewing public basket %s: %s", uuid_str, exc)
        flash(_("Error al cargar la canasta pública."), "error")
        return redirect(url_for("baskets.baskets"))


@baskets_bp.route("/public/<uuid_str>/clone", methods=["POST"])
@login_required
def clone_public_basket(uuid_str: str):
    """Clones a public basket into current authenticated user's account."""
    try:
        with get_user_session() as u_session:
            user_repo = get_user_repository(u_session)
            user_id = _resolve_user_id(user_repo)
            basket = user_repo.get_basket_by_uuid(uuid_str)
            if not basket or not basket.is_public:
                flash(_("Esta canasta no está disponible para clonar."), "error")
                return redirect(url_for("baskets.baskets")), 404

            cloned_items = [
                BasketItem(
                    ean=it.ean,
                    quantity=it.quantity,
                    selected=getattr(it, "selected", True),
                    numerator=getattr(it, "numerator", 1) or 1,
                    denominator=getattr(it, "denominator", 1) or 1,
                )
                for it in basket.items
            ]
            cloned_basket = Basket(
                user_id=user_id,
                name=f"{basket.name} (Copia)",
                is_public=False,
                items=cloned_items,
            )
            saved = user_repo.save_basket(cloned_basket)
            flash(_("Canasta copiada a tus canastas guardadas."), "success")
            return redirect(url_for("baskets.edit_basket", basket_id=saved.id))
    except Exception as exc:
        logger.error("Error cloning public basket %s: %s", uuid_str, exc)
        flash(_("Error al guardar una copia de la canasta."), "error")
        return redirect(url_for("baskets.baskets"))


@baskets_bp.route("/add-item", methods=["POST"])
@login_required
def add_item_quick():
    """Quickly adds an EAN to a user's basket from catalog or detail view."""
    try:
        basket_id = int(request.form.get("basket_id", 0))
        ean = str(request.form.get("ean", "")).strip()
        if not basket_id or not ean:
            flash(_("Datos inválidos."), "error")
            return redirect(request.referrer or url_for("catalog.index"))

        with get_user_session() as u_session:
            user_repo = get_user_repository(u_session)
            user_id = _resolve_user_id(user_repo)
            user_baskets = user_repo.get_user_baskets(user_id=user_id)
            basket = next((b for b in user_baskets if b.id == basket_id), None)
            if not basket:
                flash(_("Canasta no encontrada."), "error")
                return redirect(request.referrer or url_for("catalog.index"))

            existing = next((it for it in basket.items if it.ean == ean), None)
            if existing:
                existing.quantity += 1
            else:
                basket.items.append(
                    BasketItem(
                        ean=ean,
                        quantity=1,
                        selected=True,
                        numerator=1,
                        denominator=1,
                    )
                )
            user_repo.save_basket(basket)
            flash(
                _("Artículo agregado a la canasta '%(name)s'.", name=basket.name),
                "success",
            )
            return redirect(
                request.referrer or url_for("baskets.edit_basket", basket_id=basket.id)
            )
    except Exception as exc:
        logger.error("Error in quick add item: %s", exc)
        flash(_("Error al agregar el artículo a la canasta."), "error")
        return redirect(request.referrer or url_for("catalog.index"))
