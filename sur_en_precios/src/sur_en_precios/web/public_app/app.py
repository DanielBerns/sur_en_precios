from datetime import date
from pathlib import Path

from flask import Flask, redirect, render_template_string, request, url_for
from flask_babel import Babel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sur_en_precios.adapters.database.models_public import PublicBase
from sur_en_precios.adapters.database.models_user import UserBase
from sur_en_precios.adapters.database.repositories import (
    SqlAlchemyCatalogRepository,
    SqlAlchemyPriceRepository,
    SqlAlchemyUserRepository,
)
from sur_en_precios.config import read_config
from sur_en_precios.domain.models import ListItem, ShoppingList
from sur_en_precios.use_cases.optimize_basket import OptimizeBasketUseCase

PUBLIC_LAYOUT_HEADER = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sur en Precios — {{ _('Comparador de Precios de Supermercados') }}</title>
    <style>
        :root { --bg: #0b132b; --card: #1c2541; --accent: #48cae4; --text: #edf2f4; --success: #2ec4b6; --danger: #e63946; --warning: #ffb703; }
        body { font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 0; }
        header { background: #1c2541; padding: 1rem 2rem; display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid var(--accent); }
        header h1 { margin: 0; color: var(--accent); font-size: 1.5rem; }
        nav a { color: var(--text); text-decoration: none; margin-left: 1.5rem; font-weight: 500; }
        nav a:hover { color: var(--accent); }
        .container { max-width: 1200px; margin: 2rem auto; padding: 0 1rem; }
        .card { background: var(--card); border-radius: 12px; padding: 1.5rem; margin-bottom: 2rem; box-shadow: 0 4px 20px rgba(0,0,0,0.3); }
        .form-group { margin-bottom: 1rem; }
        input[type="text"], input[type="date"], select { width: 100%; padding: 0.75rem; border-radius: 6px; border: 1px solid #3a506b; background: #0b132b; color: white; box-sizing: border-box; }
        button, .btn { background: var(--accent); color: #0b132b; font-weight: bold; border: none; padding: 0.75rem 1.5rem; border-radius: 6px; cursor: pointer; text-decoration: none; display: inline-block; }
        button:hover, .btn:hover { opacity: 0.9; }
        table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
        th, td { text-align: left; padding: 0.75rem; border-bottom: 1px solid #3a506b; }
        th { color: var(--accent); }
        .badge { padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 0.8rem; }
        .badge-lowest { background: rgba(46, 196, 182, 0.25); color: var(--success); border: 1px solid var(--success); }
        .badge-highest { background: rgba(230, 57, 70, 0.25); color: var(--danger); border: 1px solid var(--danger); }
        .badge-ref { background: rgba(255, 183, 3, 0.25); color: var(--warning); border: 1px solid var(--warning); }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.5rem; }
    </style>
</head>
<body>
    <header>
        <h1>Sur en Precios</h1>
        <nav>
            <a href="{{ url_for('index') }}">{{ _('Buscar Productos') }}</a>
            <a href="{{ url_for('baskets') }}">{{ _('Mis Canastas') }}</a>
            <a href="{{ url_for('optimize') }}">{{ _('Optimizar Precios') }}</a>
        </nav>
    </header>
    <div class="container">
"""

PUBLIC_LAYOUT_FOOTER = """
    </div>
</body>
</html>
"""

INDEX_TEMPLATE = (
    PUBLIC_LAYOUT_HEADER
    + """
        <div class="card">
            <h2>{{ _('Buscador de Productos') }}</h2>
            <form method="GET" action="{{ url_for('index') }}">
                <div class="form-group">
                    <input type="text" name="q" value="{{ query }}" placeholder="{{ _('Buscar por nombre de producto, marca o código EAN...') }}">
                </div>
                <button type="submit">{{ _('Buscar') }}</button>
            </form>
        </div>

        {% if products %}
        <div class="card">
            <h2>{{ _('Resultados de Búsqueda') }}</h2>
            <table>
                <thead>
                    <tr>
                        <th>{{ _('Código EAN') }}</th>
                        <th>{{ _('Descripción') }}</th>
                        <th>{{ _('Marca') }}</th>
                        <th>{{ _('Categoría') }}</th>
                    </tr>
                </thead>
                <tbody>
                    {% for p in products %}
                    <tr>
                        <td><code>{{ p.ean }}</code></td>
                        <td>{{ p.name }}</td>
                        <td>{{ p.brand or '-' }}</td>
                        <td>{{ p.category or '-' }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}
"""
    + PUBLIC_LAYOUT_FOOTER
)

BASKETS_TEMPLATE = (
    PUBLIC_LAYOUT_HEADER
    + """
        <div class="card">
            <h2>{{ _('Crear Nueva Canasta de Compras') }}</h2>
            <form method="POST" action="{{ url_for('create_basket') }}">
                <div class="form-group">
                    <input type="text" name="name" placeholder="{{ _('Nombre de la canasta (ej. Almacén Semanal)') }}" required>
                </div>
                <div class="form-group">
                    <input type="text" name="eans" placeholder="{{ _('Códigos EAN separados por coma (ej. 779001, 779002)') }}" required>
                </div>
                <button type="submit">{{ _('Guardar Canasta') }}</button>
            </form>
        </div>

        <div class="card">
            <h2>{{ _('Mis Canastas Guardadas') }}</h2>
            {% for b in shopping_lists %}
            <div style="border-bottom: 1px solid #3a506b; padding: 1rem 0;">
                <h3>{{ b.name }}</h3>
                <p><strong>{{ _('Productos') }}:</strong> {{ b.items|length }} {{ _('ítems') }}</p>
                <a href="{{ url_for('optimize', list_id=b.id) }}" class="btn">{{ _('Optimizar esta Canasta') }}</a>
            </div>
            {% else %}
            <p>{{ _('No tienes canastas de compras guardadas aún.') }}</p>
            {% endfor %}
        </div>
"""
    + PUBLIC_LAYOUT_FOOTER
)

OPTIMIZE_TEMPLATE = (
    PUBLIC_LAYOUT_HEADER
    + """
        <div class="card">
            <h2>{{ _('Optimización de Canasta de Compras') }}</h2>
            <form method="GET" action="{{ url_for('optimize') }}">
                <div class="grid">
                    <div class="form-group">
                        <label>{{ _('Ciudad') }}</label>
                        <input type="text" name="city" value="{{ selected_city }}" required>
                    </div>
                    <div class="form-group">
                        <label>{{ _('Fecha') }}</label>
                        <input type="date" name="date" value="{{ selected_date_str }}" required>
                    </div>
                </div>
                <div class="form-group">
                    <label>{{ _('Códigos EAN de la Canasta') }}</label>
                    <input type="text" name="eans" value="{{ eans_str }}" placeholder="{{ _('Códigos EAN separados por coma') }}" required>
                </div>
                <button type="submit">{{ _('Calcular Mejores Precios') }}</button>
            </form>
        </div>

        {% if result %}
        {% if result.best_single_store %}
        <div class="card" style="border-left: 6px solid var(--success);">
            <h2>{{ _('Mejor Opción: Comercio Único') }}</h2>
            <h3>{{ result.best_single_store.store.chain_name }} — {{ result.best_single_store.store.store_name }}</h3>
            <p style="font-size: 1.5rem; font-weight: bold; color: var(--success);">
                {{ _('Total Canasta') }}: {{ result.best_single_store.total_price | format_currency }}
            </p>
        </div>
        {% endif %}

        {% if result.item_by_item_optimal %}
        <div class="card">
            <h2>{{ _('Asignación Óptima Producto por Producto') }}</h2>
            <table>
                <thead>
                    <tr>
                        <th>{{ _('Producto') }}</th>
                        <th>{{ _('Comercio más Barato') }}</th>
                        <th>{{ _('Precio Unitario') }}</th>
                    </tr>
                </thead>
                <tbody>
                    {% for opt in result.item_by_item_optimal %}
                    <tr>
                        <td>{{ opt.product.name }}</td>
                        <td>{{ opt.cheapest_store.chain_name }} ({{ opt.cheapest_store.store_name }})</td>
                        <td><strong>{{ opt.price | format_currency }}</strong></td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}

        {% if result.complete_stores %}
        <div class="card">
            <h2>{{ _('Matriz de Precios por Comercio') }}</h2>
            <p>{{ _('Precios expresados en Pesos Argentinos (ARS) sin centavos. El Precio de Referencia corresponde a la media geométrica.') }}</p>
            <table>
                <thead>
                    <tr>
                        <th>{{ _('Comercio') }}</th>
                        <th>{{ _('Total Canasta') }}</th>
                        <th>{{ _('Estado') }}</th>
                    </tr>
                </thead>
                <tbody>
                    {% for st in result.complete_stores %}
                    <tr>
                        <td>{{ st.store.chain_name }} — {{ st.store.store_name }}</td>
                        <td><strong>{{ st.total_price | format_currency }}</strong></td>
                        <td><span class="badge badge-lowest">{{ _('Disponibilidad 100%%') }}</span></td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}
        {% endif %}
"""
    + PUBLIC_LAYOUT_FOOTER
)


def get_locale():
    return "es_AR"


def create_public_app(workdir: Path | None = None) -> Flask:
    """Factory creating Flask public web application."""
    config = read_config(workdir_override=workdir, should_create_override=True)
    public_db_path = config.get_public_db_path()
    user_db_path = config.get_user_db_path()

    public_engine = create_engine(f"sqlite:///{public_db_path}")
    PublicBase.metadata.create_all(public_engine)

    user_engine = create_engine(f"sqlite:///{user_db_path}")
    UserBase.metadata.create_all(user_engine)

    app = Flask(__name__)
    app.secret_key = "sur_precios_public_secret_key"
    app.config["BABEL_DEFAULT_LOCALE"] = "es_AR"

    Babel(app, locale_selector=get_locale)

    @app.template_filter("format_currency")
    def format_currency(value: int | None) -> str:
        if value is None:
            return "-"
        formatted = f"{value:,}".replace(",", ".")
        return f"${formatted} ARS"

    @app.route("/")
    def index():
        query = request.args.get("q", "")
        products = []
        if query:
            with Session(public_engine) as session:
                cat_repo = SqlAlchemyCatalogRepository(session)
                products = cat_repo.search_products(query, limit=50)
        return render_template_string(INDEX_TEMPLATE, query=query, products=products)

    @app.route("/baskets")
    def baskets():
        with Session(user_engine) as session:
            user_repo = SqlAlchemyUserRepository(session)
            # Default demo user for shared public site
            shopping_lists = user_repo.get_user_shopping_lists(user_id=1)
            return render_template_string(
                BASKETS_TEMPLATE, shopping_lists=shopping_lists
            )

    @app.route("/baskets/create", methods=["POST"])
    def create_basket():
        name = request.form.get("name", "Canasta de Compras")
        eans_raw = request.form.get("eans", "")
        ean_list = [e.strip() for e in eans_raw.split(",") if e.strip()]

        with Session(user_engine) as session:
            user_repo = SqlAlchemyUserRepository(session)
            # Default demo user (creates if missing)
            demo_user = user_repo.get_user_by_email("demo@surenprecios.ar")
            if not demo_user:
                demo_user = user_repo.create_user("demo@surenprecios.ar", "pass")

            items = [ListItem(ean=ean, quantity=1) for ean in ean_list]
            new_list = ShoppingList(
                id=None, user_id=demo_user.id, name=name, items=items
            )
            user_repo.save_shopping_list(new_list)

        return redirect(url_for("baskets"))

    @app.route("/optimize")
    def optimize():
        selected_city = request.args.get("city", "Bahía Blanca")
        selected_date_str = request.args.get("date", date.today().strftime("%Y-%m-%d"))
        eans_str = request.args.get("eans", "")
        list_id = request.args.get("list_id")

        if list_id and not eans_str:
            with Session(user_engine) as session:
                user_repo = SqlAlchemyUserRepository(session)
                lists = user_repo.get_user_shopping_lists(user_id=1)
                target_list = next(
                    (
                        list_obj
                        for list_obj in lists
                        if str(list_obj.id) == str(list_id)
                    ),
                    None,
                )
                if target_list:
                    eans_str = ", ".join([item.ean for item in target_list.items])

        result = None
        if eans_str:
            target_date = date.fromisoformat(selected_date_str)
            ean_list = [e.strip() for e in eans_str.split(",") if e.strip()]
            requested_items = [ListItem(ean=ean, quantity=1) for ean in ean_list]

            with Session(public_engine) as session:
                cat_repo = SqlAlchemyCatalogRepository(session)
                price_repo = SqlAlchemyPriceRepository(session)
                use_case = OptimizeBasketUseCase(cat_repo, price_repo)
                result = use_case.execute(selected_city, target_date, requested_items)

        return render_template_string(
            OPTIMIZE_TEMPLATE,
            selected_city=selected_city,
            selected_date_str=selected_date_str,
            eans_str=eans_str,
            result=result,
        )

    return app


if __name__ == "__main__":
    public_app = create_public_app()
    public_app.run(port=5000, debug=True)
