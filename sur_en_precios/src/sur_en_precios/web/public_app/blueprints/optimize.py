import json
import logging
import re
from datetime import date
from typing import List

from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    render_template,
    request,
    session,
)
from flask_babel import gettext as _

from sur_en_precios.domain.models_user import BasketItem
from sur_en_precios.domain.services import BasketPriceReportService
from sur_en_precios.use_cases.optimize_basket import OptimizeBasketUseCase
from sur_en_precios.web.public_app.database import (
    get_catalog_repository,
    get_price_repository,
    get_public_session,
    get_user_repository,
    get_user_session,
)
from sur_en_precios.web.public_app.schemas import OptimizeQuerySchema

logger = logging.getLogger("sur_en_precios.public_app.optimize")

optimize_bp = Blueprint("optimize", __name__)


@optimize_bp.route("/optimize")
def optimize():
    params = OptimizeQuerySchema(
        city=request.args.get("city"),
        date=request.args.get("date"),
        eans=request.args.get("eans", "").strip(),
        list_id=request.args.get("list_id"),
        public_uuid=request.args.get("public_uuid"),
    )
    list_id = params.list_id
    public_uuid = params.public_uuid
    eans_str = params.eans

    config = current_app.config["APP_CONFIG"]

    with get_public_session() as pub_session:
        cat_repo = get_catalog_repository(pub_session)
        price_repo = get_price_repository(pub_session)

        region = config.get_region()
        cities = cat_repo.get_cities_for_region(region)

        # Latest price date from DB
        latest_date = price_repo.get_latest_price_date()
        default_date_str = (
            latest_date.strftime("%Y-%m-%d")
            if latest_date
            else date.today().strftime("%Y-%m-%d")
        )
        selected_date_str = params.date if params.date else default_date_str

        # Resolve selected city: default to first city in database region
        req_city = params.city
        if req_city:
            matching_city = next(
                (c for c in cities if c.lower() == req_city.strip().lower()), None
            )
            if matching_city:
                selected_city = matching_city
            else:
                selected_city = req_city.strip()
                if selected_city not in cities:
                    cities.append(selected_city)
        elif cities:
            selected_city = next(
                (c for c in cities if "comodoro" in c.lower()), cities[0]
            )
        else:
            selected_city = ""

    user_baskets = []
    target_list = None
    requested_items: List[BasketItem] = []
    try:
        with get_user_session() as u_session:
            user_repo = get_user_repository(u_session)
            user_id = session.get("user_id")
            if user_id:
                user_baskets = user_repo.get_user_baskets(user_id=user_id)

            if public_uuid:
                target_list = user_repo.get_basket_by_uuid(public_uuid)
                if target_list and (
                    target_list.is_public
                    or session.get("is_admin")
                    or (user_id and target_list.user_id == user_id)
                ):
                    requested_items = [
                        it
                        for it in target_list.items
                        if getattr(it, "selected", True) is not False
                    ]
                    if not eans_str:
                        eans_str = ", ".join([item.ean for item in requested_items])

            elif list_id:
                target_list = next(
                    (
                        list_obj
                        for list_obj in user_baskets
                        if str(list_obj.id) == str(list_id)
                    ),
                    None,
                )
                if not target_list and session.get("is_admin"):
                    # Admin can optimize any basket
                    all_baskets = user_repo.get_all_baskets()
                    target_list = next(
                        (b for b in all_baskets if str(b.id) == str(list_id)), None
                    )

                if target_list:
                    requested_items = [
                        it
                        for it in target_list.items
                        if getattr(it, "selected", True) is not False
                    ]
                    if not eans_str:
                        eans_str = ", ".join([item.ean for item in requested_items])

    except Exception as exc:
        logger.error("Error loading user baskets for optimize: %s", exc)

    result = None
    requested_products = []
    unpriced_items = []

    if eans_str:
        try:
            target_date = date.fromisoformat(selected_date_str)
            ean_list = [e.strip() for e in re.split(r"[\s,]+", eans_str) if e.strip()]

            current_eans = [it.ean for it in requested_items]
            if not requested_items or current_eans != ean_list:
                requested_items = [
                    BasketItem(
                        ean=ean,
                        quantity=1,
                        selected=True,
                        numerator=1,
                        denominator=1,
                    )
                    for ean in ean_list
                ]

            with get_public_session() as pub_session:
                cat_repo = get_catalog_repository(pub_session)
                price_repo = get_price_repository(pub_session)
                use_case = OptimizeBasketUseCase(cat_repo, price_repo)
                result = use_case.execute(selected_city, target_date, requested_items)

                for item in requested_items:
                    art = cat_repo.get_article_by_ean(item.ean)
                    requested_products.append(
                        {
                            "ean": item.ean,
                            "name": getattr(art, "name", f"Producto {item.ean}")
                            if art
                            else f"Producto {item.ean}",
                            "brand": getattr(art, "brand_name", "") if art else "",
                        }
                    )

                priced_eans = {
                    opt.product.ean for opt in (result.item_by_item_optimal or [])
                }
                for prod in requested_products:
                    if prod["ean"] not in priced_eans:
                        unpriced_items.append(prod)

        except Exception as exc:
            logger.error("Optimization calculation error: %s", exc)
            flash(_("Error al calcular los precios óptimos para la canasta."), "error")

    is_json = (
        request.args.get("format") == "json"
        or request.args.get("download") == "json"
        or (request.endpoint and request.endpoint.endswith("export_optimize_json"))
    )
    if is_json:
        if not result:
            return Response(
                json.dumps(
                    {
                        "error": _(
                            "No se encontraron datos de optimización o no se especificaron artículos para la canasta."
                        )
                    },
                    ensure_ascii=False,
                ),
                status=400,
                mimetype="application/json",
            )
        json_str = BasketPriceReportService.export_to_json(
            result=result,
            basket=target_list,
            unpriced_items=unpriced_items,
        )
        clean_city = re.sub(r"[^a-zA-Z0-9_\-]", "_", selected_city)
        filename = f"reporte_precios_{clean_city}_{selected_date_str}.json"
        if target_list and getattr(target_list, "name", None):
            clean_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", target_list.name)
            filename = (
                f"reporte_precios_{clean_name}_{clean_city}_{selected_date_str}.json"
            )
        elif public_uuid:
            filename = f"reporte_precios_publica_{public_uuid[:8]}_{clean_city}_{selected_date_str}.json"
        return Response(
            json_str,
            mimetype="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return render_template(
        "optimize/optimize.html",
        selected_city=selected_city,
        selected_date_str=selected_date_str,
        cities=cities,
        eans_str=eans_str,
        list_id=list_id,
        public_uuid=public_uuid,
        user_baskets=user_baskets,
        result=result,
        requested_products=requested_products,
        unpriced_items=unpriced_items,
    )


@optimize_bp.route("/optimize/export-json")
def export_optimize_json():
    """Exports optimize price report as a JSON file."""
    return optimize()
