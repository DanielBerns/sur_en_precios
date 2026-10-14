import logging
from datetime import date
from pathlib import Path
from typing import Dict, List

from flask import (
    Flask,
    Response,
    flash,
    jsonify,
    redirect,
    render_template_string,
    request,
    url_for,
)
from flask_babel import Babel
from flask_babel import gettext as _
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sur_en_precios.adapters.database.repositories import (
    SqlAlchemyCatalogRepository,
    SqlAlchemyPriceRepository,
    SqlAlchemyUserRepository,
)
from sur_en_precios.config import read_config
from sur_en_precios.domain.models_public import ArticleCard, PublicBase
from sur_en_precios.domain.models_user import Basket, BasketItem, UserBase
from sur_en_precios.domain.services import (
    BasketYamlService,
    YamlValidationError,
)
from sur_en_precios.use_cases.optimize_basket import OptimizeBasketUseCase

logger = logging.getLogger("sur_en_precios.public_app")

PUBLIC_LAYOUT_HEADER = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sur en Precios — {{ _('Comparador de Precios de Supermercados') }}</title>
    <style>
        :root { --bg: #0b132b; --card: #1c2541; --accent: #48cae4; --text: #edf2f4; --success: #2ec4b6; --danger: #e63946; --warning: #ffb703; --muted: #6fffe9; }
        body { font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 0; }
        header { background: #1c2541; padding: 1rem 2rem; display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid var(--accent); }
        header h1 { margin: 0; color: var(--accent); font-size: 1.5rem; }
        nav a { color: var(--text); text-decoration: none; margin-left: 1.5rem; font-weight: 500; }
        nav a:hover { color: var(--accent); }
        .container { max-width: 1200px; margin: 2rem auto; padding: 0 1rem; }
        .card { background: var(--card); border-radius: 12px; padding: 1.5rem; margin-bottom: 2rem; box-shadow: 0 4px 20px rgba(0,0,0,0.3); }
        .form-group { margin-bottom: 1rem; }
        input[type="text"], input[type="date"], input[type="number"], select, textarea { width: 100%; padding: 0.75rem; border-radius: 6px; border: 1px solid #3a506b; background: #0b132b; color: white; box-sizing: border-box; }
        button, .btn { background: var(--accent); color: #0b132b; font-weight: bold; border: none; padding: 0.6rem 1.2rem; border-radius: 6px; cursor: pointer; text-decoration: none; display: inline-block; font-size: 0.95rem; }
        button:hover, .btn:hover { opacity: 0.9; }
        .btn-secondary { background: #3a506b; color: var(--text); }
        .btn-success { background: var(--success); color: #0b132b; }
        .btn-danger { background: var(--danger); color: white; padding: 0.4rem 0.8rem; font-size: 0.85rem; }
        .btn-sm { padding: 0.35rem 0.75rem; font-size: 0.85rem; }
        table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
        th, td { text-align: left; padding: 0.75rem; border-bottom: 1px solid #3a506b; }
        th { color: var(--accent); }
        .badge { padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 0.8rem; display: inline-block; }
        .badge-lowest { background: rgba(46, 196, 182, 0.25); color: var(--success); border: 1px solid var(--success); }
        .badge-highest { background: rgba(230, 57, 70, 0.25); color: var(--danger); border: 1px solid var(--danger); }
        .badge-ref { background: rgba(255, 183, 3, 0.25); color: var(--warning); border: 1px solid var(--warning); }
        .badge-public { background: rgba(46, 196, 182, 0.2); color: var(--success); border: 1px solid var(--success); }
        .badge-private { background: rgba(237, 242, 244, 0.15); color: #a0aec0; border: 1px solid #718096; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.5rem; }
        .editor-grid { display: grid; grid-template-columns: 1.6fr 1.2fr; gap: 1.5rem; align-items: start; }
        @media (max-width: 900px) { .editor-grid { grid-template-columns: 1fr; } }
        .share-banner { background: #13223f; border: 1px dashed var(--accent); border-radius: 8px; padding: 1rem; margin: 1rem 0; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 1rem; }
        .share-banner code { background: #0b132b; padding: 4px 8px; border-radius: 4px; color: var(--accent); font-size: 0.95rem; }
        .search-results-box { max-height: 480px; overflow-y: auto; margin-top: 1rem; border: 1px solid #3a506b; border-radius: 6px; padding: 0.5rem; }
        .result-card { background: #13223f; border: 1px solid #3a506b; border-radius: 6px; padding: 0.75rem; margin-bottom: 0.5rem; display: flex; justify-content: space-between; align-items: center; }
        .result-card:hover { border-color: var(--accent); }
        .toggle-switch-wrapper { display: flex; align-items: center; gap: 0.75rem; margin: 0.5rem 0; }
        .toggle-switch-wrapper input[type="checkbox"] { transform: scale(1.3); cursor: pointer; }
        .flash-card { padding: 1rem; border-radius: 8px; margin-bottom: 1.5rem; font-weight: 500; }
        .flash-success { background: rgba(46, 196, 182, 0.2); border-left: 5px solid var(--success); color: var(--text); }
        .flash-error { background: rgba(230, 57, 70, 0.2); border-left: 5px solid var(--danger); color: var(--text); }
        .flash-warning { background: rgba(255, 183, 3, 0.2); border-left: 5px solid var(--warning); color: var(--text); }
        .mode-selector { display: flex; gap: 1rem; margin-bottom: 0.75rem; font-size: 0.9rem; }
        .mode-selector label { cursor: pointer; display: flex; align-items: center; gap: 0.35rem; }
    </style>
    <script>
        function copyText(text, btn) {
            navigator.clipboard.writeText(text).then(function() {
                const originalText = btn.innerText;
                btn.innerText = "¡Copiado!";
                btn.style.background = "var(--success)";
                setTimeout(function() {
                    btn.innerText = originalText;
                    btn.style.background = "";
                }, 2000);
            }).catch(function(err) {
                prompt("Copiar:", text);
            });
        }
    </script>
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
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="flash-card flash-{{ category }}">
                {{ message }}
              </div>
            {% endfor %}
          {% endif %}
        {% endwith %}
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
                    <input type="text" name="q" value="{{ query }}" placeholder="{{ _('Buscar por descripción, marca o código EAN...') }}">
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
                        <td>{{ p.brand_name or '-' }}</td>
                        <td>{{ p.category_name or '-' }}</td>
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
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem;">
            <h2>{{ _('Mis Canastas de Compras') }}</h2>
            <a href="{{ url_for('new_basket') }}" class="btn btn-success">+ {{ _('Crear Nueva Canasta') }}</a>
        </div>

        <div class="grid">
            <!-- Open Shared Public Basket Card -->
            <div class="card">
                <h3>{{ _('Abrir Canasta Compartida') }}</h3>
                <p>{{ _('Si recibiste el código UUID de una canasta pública, ingrésalo aquí:') }}</p>
                <form method="GET" action="{{ url_for('open_public_by_uuid') }}">
                    <div class="form-group">
                        <input type="text" name="uuid" placeholder="{{ _('Pegar UUID (ej. 3fa85f64-5717-4562-b3fc-...)') }}" required>
                    </div>
                    <button type="submit" class="btn btn-secondary">{{ _('Abrir Canasta') }}</button>
                </form>
            </div>

            <!-- Upload Basket YAML Card -->
            <div class="card">
                <h3>{{ _('Importar Canasta (YAML)') }}</h3>
                <p>{{ _('Sube un archivo de canasta en formato YAML:') }}</p>
                <form method="POST" action="{{ url_for('import_basket') }}" enctype="multipart/form-data">
                    <div class="form-group">
                        <input type="file" name="yaml_file" accept=".yaml,.yml" required style="padding: 0.5rem; background: #0b132b; border: 1px solid #3a506b; border-radius: 6px; width: 100%;">
                    </div>
                    <button type="submit" class="btn btn-secondary">{{ _('Subir e Importar') }}</button>
                </form>
            </div>
        </div>

        <div class="card">
            <h3>{{ _('Mis Canastas Guardadas') }}</h3>
            {% if shopping_lists %}
            <table>
                <thead>
                    <tr>
                        <th>{{ _('Nombre de la Canasta') }}</th>
                        <th>{{ _('Visibilidad') }}</th>
                        <th>{{ _('Artículos') }}</th>
                        <th>{{ _('Acciones') }}</th>
                    </tr>
                </thead>
                <tbody>
                    {% for b in shopping_lists %}
                    <tr>
                        <td><strong>{{ b.name }}</strong></td>
                        <td>
                            {% if b.is_public %}
                            <span class="badge badge-public">{{ _('Pública') }}</span>
                            {% else %}
                            <span class="badge badge-private">{{ _('Privada') }}</span>
                            {% endif %}
                        </td>
                        <td>{{ b.items|length }} {{ _('ítems') }}</td>
                        <td style="white-space: nowrap;">
                            <a href="{{ url_for('edit_basket', basket_id=b.id) }}" class="btn btn-sm">{{ _('Editar') }}</a>
                            <a href="{{ url_for('optimize', list_id=b.id) }}" class="btn btn-sm btn-success">{{ _('Optimizar') }}</a>
                            <a href="{{ url_for('export_basket', basket_id=b.id) }}" class="btn btn-sm btn-secondary">{{ _('YAML') }}</a>
                            <form method="POST" action="{{ url_for('delete_basket', basket_id=b.id) }}" style="display:inline;" onsubmit="return confirm('¿Eliminar esta canasta?');">
                                <button type="submit" class="btn btn-danger btn-sm">{{ _('Eliminar') }}</button>
                            </form>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <p>{{ _('No tienes canastas de compras guardadas aún.') }}</p>
            {% endif %}
        </div>
"""
    + PUBLIC_LAYOUT_FOOTER
)

BASKET_EDITOR_TEMPLATE = (
    PUBLIC_LAYOUT_HEADER
    + """
        <div style="margin-bottom: 1rem;">
            <a href="{{ url_for('baskets') }}" style="color: var(--accent); text-decoration: none;">&larr; {{ _('Volver a Mis Canastas') }}</a>
        </div>

        <form method="POST" action="{{ url_for('save_basket', basket_id=basket.id) }}" id="basket_form">
            <input type="hidden" name="eans" id="eans_input" value="{{ eans_csv }}">

            <div class="card">
                <div style="display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 1rem;">
                    <div style="flex: 1; min-width: 250px;">
                        <label><strong>{{ _('Nombre de la Canasta') }}:</strong></label>
                        <input type="text" name="name" value="{{ basket.name }}" required style="font-size: 1.1rem; font-weight: bold; margin-top: 0.25rem;">
                    </div>
                    <div class="toggle-switch-wrapper">
                        <label>
                            <input type="checkbox" name="is_public" value="1" {% if basket.is_public %}checked{% endif %}>
                            <strong>{{ _('Canasta Pública') }}</strong>
                        </label>
                        <span style="font-size: 0.85rem; color: #a0aec0;">({{ _('Permite compartir con otros mediante UUID') }})</span>
                    </div>
                    <div>
                        <button type="submit" class="btn btn-success">{{ _('Guardar Cambios') }}</button>
                        <a href="{{ url_for('optimize', list_id=basket.id) }}" class="btn">{{ _('Optimizar Precios') }}</a>
                        <a href="{{ url_for('export_basket', basket_id=basket.id) }}" class="btn btn-secondary">{{ _('Descargar YAML') }}</a>
                    </div>
                </div>

                {% if basket.is_public and basket.uuid %}
                <div class="share-banner">
                    <div>
                        <strong>{{ _('UUID para Compartir:') }}</strong>
                        <code>{{ basket.uuid }}</code>
                    </div>
                    <div>
                        <button type="button" class="btn btn-secondary btn-sm" onclick="copyText('{{ basket.uuid }}', this)">{{ _('Copiar UUID') }}</button>
                        <button type="button" class="btn btn-secondary btn-sm" onclick="copyText('{{ url_for('view_public_basket', uuid_str=basket.uuid, _external=True) }}', this)">{{ _('Copiar Enlace') }}</button>
                    </div>
                </div>
                {% endif %}
            </div>

            <div class="editor-grid">
                <!-- Left Column: Basket Items Table -->
                <div class="card">
                    <h3>{{ _('Artículos en la Canasta') }} (<span id="items_count">{{ items_data|length }}</span>)</h3>
                    <p style="font-size: 0.85rem; color: #a0aec0;">
                        {{ _('Selecciona/deselecciona para incluir o excluir artículos temporalmente de la optimización.') }}
                    </p>

                    <div style="overflow-x: auto;">
                        <table id="basket_items_table">
                            <thead>
                                <tr>
                                    <th style="width: 40px; text-align: center;">{{ _('Activo') }}</th>
                                    <th>{{ _('Producto') }}</th>
                                    <th style="width: 80px;">{{ _('Cant.') }}</th>
                                    <th style="width: 100px;">{{ _('Fracción (N/D)') }}</th>
                                    <th style="width: 60px;">{{ _('Acción') }}</th>
                                </tr>
                            </thead>
                            <tbody id="basket_items_tbody">
                                {% for item in items_data %}
                                <tr id="row_{{ item.ean }}">
                                    <td style="text-align: center;">
                                        <input type="checkbox" name="item_selected_{{ item.ean }}" value="1" {% if item.selected %}checked{% endif %}>
                                    </td>
                                    <td>
                                        <div><strong>{{ item.name }}</strong></div>
                                        <div style="font-size: 0.8rem; color: #a0aec0;">
                                            <span>{{ item.brand or '-' }}</span> |
                                            <span>{{ item.category or '-' }}</span> |
                                            <code>{{ item.ean }}</code>
                                        </div>
                                    </td>
                                    <td>
                                        <input type="number" name="item_quantity_{{ item.ean }}" value="{{ item.quantity }}" min="1" required style="width: 70px; padding: 0.4rem;">
                                    </td>
                                    <td>
                                        <div style="display: flex; align-items: center; gap: 4px;">
                                            <input type="number" name="item_numerator_{{ item.ean }}" value="{{ item.numerator }}" min="1" required style="width: 45px; padding: 0.4rem;">
                                            <span>/</span>
                                            <input type="number" name="item_denominator_{{ item.ean }}" value="{{ item.denominator }}" min="1" required style="width: 45px; padding: 0.4rem;">
                                        </div>
                                    </td>
                                    <td>
                                        <button type="button" class="btn btn-danger btn-sm" onclick="removeItem('{{ item.ean }}')">&times;</button>
                                    </td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                    <div id="no_items_msg" style="{% if items_data %}display: none;{% endif %} padding: 2rem 0; text-align: center; color: #a0aec0;">
                        {{ _('No hay artículos en la canasta. Utiliza el buscador para agregar productos.') }}
                    </div>
                </div>

                <!-- Right Column: Product Search Box -->
                <div class="card">
                    <h3>{{ _('Buscador de Artículos') }}</h3>
                    <p style="font-size: 0.85rem; color: #a0aec0;">
                        {{ _('Busca por descripción, marca o código EAN. Puedes elegir búsqueda aproximada o exacta.') }}
                    </p>

                    <div class="mode-selector">
                        <label>
                            <input type="radio" name="search_mode" value="fuzzy" checked id="mode_fuzzy">
                            {{ _('Aproximada (Fuzzy)') }}
                        </label>
                        <label>
                            <input type="radio" name="search_mode" value="exact" id="mode_exact">
                            {{ _('Exacta') }}
                        </label>
                    </div>

                    <div style="display: flex; gap: 0.5rem;">
                        <input type="text" id="search_input" placeholder="{{ _('Buscar producto (ej. leche, arroz, quilmes)...') }}" onkeydown="if(event.key==='Enter'){event.preventDefault();searchArticles();}">
                        <button type="button" onclick="searchArticles()" class="btn">{{ _('Buscar') }}</button>
                    </div>

                    <div class="search-results-box" id="search_results_container">
                        <div id="search_placeholder" style="text-align: center; padding: 2rem 0; color: #a0aec0;">
                            {{ _('Escribe un término y haz clic en Buscar.') }}
                        </div>
                    </div>
                </div>
            </div>
        </form>

        <script>
            let eanSet = new Set({{ eans_list | tojson }});

            function updateEansCsv() {
                const list = Array.from(eanSet);
                document.getElementById('eans_input').value = list.join(',');
                document.getElementById('items_count').innerText = list.length;
                const noItemsMsg = document.getElementById('no_items_msg');
                if (list.length === 0) {
                    noItemsMsg.style.display = 'block';
                } else {
                    noItemsMsg.style.display = 'none';
                }
            }

            function removeItem(ean) {
                const row = document.getElementById('row_' + ean);
                if (row) {
                    row.remove();
                    eanSet.delete(ean);
                    updateEansCsv();
                }
            }

            function addItemToBasket(ean, name, brand, category) {
                if (eanSet.has(ean)) {
                    const qtyInput = document.querySelector('input[name="item_quantity_' + ean + '"]');
                    if (qtyInput) {
                        qtyInput.value = parseInt(qtyInput.value || 1) + 1;
                        qtyInput.style.borderColor = 'var(--accent)';
                        setTimeout(() => qtyInput.style.borderColor = '#3a506b', 1000);
                    }
                    return;
                }

                eanSet.add(ean);
                updateEansCsv();

                const tbody = document.getElementById('basket_items_tbody');
                const tr = document.createElement('tr');
                tr.id = 'row_' + ean;
                tr.innerHTML = `
                    <td style="text-align: center;">
                        <input type="checkbox" name="item_selected_${ean}" value="1" checked>
                    </td>
                    <td>
                        <div><strong>${name}</strong></div>
                        <div style="font-size: 0.8rem; color: #a0aec0;">
                            <span>${brand || '-'}</span> |
                            <span>${category || '-'}</span> |
                            <code>${ean}</code>
                        </div>
                    </td>
                    <td>
                        <input type="number" name="item_quantity_${ean}" value="1" min="1" required style="width: 70px; padding: 0.4rem;">
                    </td>
                    <td>
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <input type="number" name="item_numerator_${ean}" value="1" min="1" required style="width: 45px; padding: 0.4rem;">
                            <span>/</span>
                            <input type="number" name="item_denominator_${ean}" value="1" min="1" required style="width: 45px; padding: 0.4rem;">
                        </div>
                    </td>
                    <td>
                        <button type="button" class="btn btn-danger btn-sm" onclick="removeItem('${ean}')">&times;</button>
                    </td>
                `;
                tbody.appendChild(tr);
            }

            function searchArticles() {
                const q = document.getElementById('search_input').value.trim();
                if (!q) return;

                const mode = document.getElementById('mode_exact').checked ? 'exact' : 'fuzzy';
                const container = document.getElementById('search_results_container');
                container.innerHTML = '<div style="text-align: center; padding: 2rem 0; color: var(--accent);">Buscando productos...</div>';

                fetch('{{ url_for("api_search_articles") }}?q=' + encodeURIComponent(q) + '&mode=' + mode)
                    .then(r => r.json())
                    .then(data => {
                        if (!data || data.length === 0) {
                            container.innerHTML = '<div style="text-align: center; padding: 2rem 0; color: #a0aec0;">No se encontraron artículos que coincidan.</div>';
                            return;
                        }
                        container.innerHTML = '';
                        data.forEach(item => {
                            const card = document.createElement('div');
                            card.className = 'result-card';
                            const safeName = (item.name || '').replace(/'/g, "\\\\'");
                            const safeBrand = (item.brand || '').replace(/'/g, "\\\\'");
                            const safeCat = (item.category || '').replace(/'/g, "\\\\'");

                            card.innerHTML = `
                                <div style="flex: 1; padding-right: 0.5rem;">
                                    <div style="font-weight: bold; font-size: 0.95rem;">${item.name}</div>
                                    <div style="font-size: 0.8rem; color: #a0aec0; margin-top: 2px;">
                                        <span>${item.brand || '-'}</span> | <span>${item.category || '-'}</span> | <code>${item.ean}</code>
                                    </div>
                                </div>
                                <div>
                                    <button type="button" class="btn btn-sm btn-success" onclick="addItemToBasket('${item.ean}', '${safeName}', '${safeBrand}', '${safeCat}')">+ Agregar</button>
                                </div>
                            `;
                            container.appendChild(card);
                        });
                    })
                    .catch(err => {
                        container.innerHTML = '<div style="text-align: center; padding: 2rem 0; color: var(--danger);">Error al buscar artículos.</div>';
                    });
            }
        </script>
"""
    + PUBLIC_LAYOUT_FOOTER
)

PUBLIC_BASKET_VIEW_TEMPLATE = (
    PUBLIC_LAYOUT_HEADER
    + """
        <div style="margin-bottom: 1rem;">
            <a href="{{ url_for('baskets') }}" style="color: var(--accent); text-decoration: none;">&larr; {{ _('Ir a Mis Canastas') }}</a>
        </div>

        <div class="card">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 1rem;">
                <div>
                    <h2>{{ _('Canasta Compartida') }}: {{ basket.name }}</h2>
                    <span class="badge badge-public">{{ _('Canasta Pública') }}</span>
                    <div style="margin-top: 0.5rem;">
                        <strong>UUID:</strong> <code>{{ basket.uuid }}</code>
                    </div>
                </div>
                <div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
                    <button type="button" class="btn btn-secondary btn-sm" onclick="copyText('{{ basket.uuid }}', this)">{{ _('Copiar UUID') }}</button>
                    <button type="button" class="btn btn-secondary btn-sm" onclick="copyText(window.location.href, this)">{{ _('Copiar Enlace') }}</button>
                    <a href="{{ url_for('export_public_basket', uuid_str=basket.uuid) }}" class="btn btn-secondary btn-sm">{{ _('Descargar YAML') }}</a>
                    <a href="{{ url_for('optimize', public_uuid=basket.uuid) }}" class="btn btn-success btn-sm">{{ _('Optimizar Precios') }}</a>
                    <form method="POST" action="{{ url_for('clone_public_basket', uuid_str=basket.uuid) }}" style="display:inline;">
                        <button type="submit" class="btn btn-sm">{{ _('Guardar en Mis Canastas') }}</button>
                    </form>
                </div>
            </div>
        </div>

        <div class="card">
            <h3>{{ _('Artículos de la Canasta') }} ({{ items_data|length }})</h3>
            <table>
                <thead>
                    <tr>
                        <th>{{ _('Código EAN') }}</th>
                        <th>{{ _('Descripción') }}</th>
                        <th>{{ _('Marca') }}</th>
                        <th>{{ _('Categoría') }}</th>
                        <th>{{ _('Cantidad') }}</th>
                        <th>{{ _('Proporción') }}</th>
                    </tr>
                </thead>
                <tbody>
                    {% for it in items_data %}
                    <tr>
                        <td><code>{{ it.ean }}</code></td>
                        <td><strong>{{ it.name }}</strong></td>
                        <td>{{ it.brand or '-' }}</td>
                        <td>{{ it.category or '-' }}</td>
                        <td>{{ it.quantity }}</td>
                        <td>{{ it.numerator }}/{{ it.denominator }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
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
                        <td><span class="badge badge-lowest">{{ _('Disponibilidad 100%') }}</span></td>
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


def _get_or_create_demo_user(user_repo: SqlAlchemyUserRepository):
    user = user_repo.get_user_by_email("demo@surenprecios.ar")
    if not user:
        user = user_repo.create_user("demo@surenprecios.ar", "pass")
    return user


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
            try:
                with Session(public_engine) as session:
                    cat_repo = SqlAlchemyCatalogRepository(session)
                    products = cat_repo.search_articles(query, limit=50, mode="fuzzy")
            except Exception as exc:
                logger.error("Error searching in index: %s", exc, exc_info=True)
                flash(_("Ocurrió un error al realizar la búsqueda."), "error")
        return render_template_string(INDEX_TEMPLATE, query=query, products=products)

    @app.route("/baskets")
    def baskets():
        try:
            with Session(user_engine) as session:
                user_repo = SqlAlchemyUserRepository(session)
                demo_user = _get_or_create_demo_user(user_repo)
                shopping_lists = user_repo.get_user_baskets(user_id=demo_user.id)
                return render_template_string(
                    BASKETS_TEMPLATE, shopping_lists=shopping_lists
                )
        except Exception as exc:
            logger.error("Error loading baskets: %s", exc, exc_info=True)
            flash(_("Error al cargar las canastas."), "error")
            return render_template_string(BASKETS_TEMPLATE, shopping_lists=[])

    @app.route("/baskets/new")
    def new_basket():
        try:
            with Session(user_engine) as session:
                user_repo = SqlAlchemyUserRepository(session)
                demo_user = _get_or_create_demo_user(user_repo)
                draft = Basket(
                    user_id=demo_user.id,
                    name=_("Nueva Canasta"),
                    is_public=False,
                    items=[],
                )
                saved = user_repo.save_basket(draft)
                return redirect(url_for("edit_basket", basket_id=saved.id))
        except Exception as exc:
            logger.error("Error creating new basket: %s", exc, exc_info=True)
            flash(_("Error al crear una nueva canasta."), "error")
            return redirect(url_for("baskets"))

    @app.route("/baskets/create", methods=["POST"])
    def create_basket():
        try:
            name = (
                request.form.get("name", "Canasta de Compras").strip()
                or "Canasta de Compras"
            )
            eans_raw = request.form.get("eans", "")
            ean_list = [e.strip() for e in eans_raw.split(",") if e.strip()]

            with Session(user_engine) as session:
                user_repo = SqlAlchemyUserRepository(session)
                demo_user = _get_or_create_demo_user(user_repo)

                items = [
                    BasketItem(
                        ean=ean, quantity=1, selected=True, numerator=1, denominator=1
                    )
                    for ean in ean_list
                ]
                new_basket = Basket(
                    id=None,
                    user_id=demo_user.id,
                    name=name,
                    items=items,
                    is_public=False,
                )
                saved = user_repo.save_basket(new_basket)
                return redirect(url_for("edit_basket", basket_id=saved.id))
        except Exception as exc:
            logger.error("Error creating basket from form: %s", exc, exc_info=True)
            flash(_("Error al guardar la canasta."), "error")
            return redirect(url_for("baskets"))

    @app.route("/baskets/<int:basket_id>/edit")
    def edit_basket(basket_id: int):
        try:
            with Session(user_engine) as user_session:
                user_repo = SqlAlchemyUserRepository(user_session)
                demo_user = _get_or_create_demo_user(user_repo)
                user_baskets = user_repo.get_user_baskets(user_id=demo_user.id)
                basket = next((b for b in user_baskets if b.id == basket_id), None)
                if not basket:
                    flash(_("Canasta no encontrada."), "error")
                    return redirect(url_for("baskets"))

                with Session(public_engine) as pub_session:
                    cat_repo = SqlAlchemyCatalogRepository(pub_session)
                    items_data = []
                    eans_list = []
                    for item in basket.items:
                        eans_list.append(item.ean)
                        card = cat_repo.get_article_by_ean(item.ean)
                        items_data.append(
                            {
                                "ean": item.ean,
                                "name": card.name if card else f"Producto {item.ean}",
                                "brand": card.brand_name if card else "",
                                "category": card.category_name if card else "",
                                "quantity": item.quantity,
                                "selected": getattr(item, "selected", True)
                                is not False,
                                "numerator": getattr(item, "numerator", 1) or 1,
                                "denominator": getattr(item, "denominator", 1) or 1,
                            }
                        )

                return render_template_string(
                    BASKET_EDITOR_TEMPLATE,
                    basket=basket,
                    items_data=items_data,
                    eans_list=eans_list,
                    eans_csv=",".join(eans_list),
                )
        except Exception as exc:
            logger.error("Error loading basket editor: %s", exc, exc_info=True)
            flash(_("Ocurrió un error al cargar el editor de canasta."), "error")
            return redirect(url_for("baskets"))

    @app.route("/baskets/<int:basket_id>/save", methods=["POST"])
    def save_basket(basket_id: int):
        try:
            with Session(user_engine) as session:
                user_repo = SqlAlchemyUserRepository(session)
                demo_user = _get_or_create_demo_user(user_repo)
                user_baskets = user_repo.get_user_baskets(user_id=demo_user.id)
                basket = next((b for b in user_baskets if b.id == basket_id), None)
                if not basket:
                    flash(_("Canasta no encontrada."), "error")
                    return redirect(url_for("baskets"))

                name = request.form.get("name", "").strip() or basket.name
                is_public = request.form.get("is_public") == "1"

                eans_raw = request.form.get("eans", "")
                ean_list = [e.strip() for e in eans_raw.split(",") if e.strip()]

                updated_items: List[BasketItem] = []
                for ean in ean_list:
                    qty_str = request.form.get(f"item_quantity_{ean}", "1")
                    sel_str = request.form.get(f"item_selected_{ean}")
                    num_str = request.form.get(f"item_numerator_{ean}", "1")
                    den_str = request.form.get(f"item_denominator_{ean}", "1")

                    try:
                        qty = max(1, int(qty_str))
                    except ValueError:
                        qty = 1

                    try:
                        num = max(1, int(num_str))
                    except ValueError:
                        num = 1

                    try:
                        den = int(den_str)
                        if den <= 0:
                            den = 1
                    except ValueError:
                        den = 1

                    selected = sel_str == "1"
                    updated_items.append(
                        BasketItem(
                            ean=ean,
                            quantity=qty,
                            selected=selected,
                            numerator=num,
                            denominator=den,
                        )
                    )

                basket.name = name
                basket.is_public = is_public
                basket.items = updated_items

                user_repo.save_basket(basket)
                flash(_("Canasta guardada exitosamente."), "success")
                return redirect(url_for("edit_basket", basket_id=basket.id))
        except Exception as exc:
            logger.error("Error saving basket %d: %s", basket_id, exc, exc_info=True)
            flash(_("Error al guardar los cambios en la canasta."), "error")
            return redirect(url_for("edit_basket", basket_id=basket_id))

    @app.route("/baskets/<int:basket_id>/delete", methods=["POST"])
    def delete_basket(basket_id: int):
        try:
            with Session(user_engine) as session:
                user_repo = SqlAlchemyUserRepository(session)
                demo_user = _get_or_create_demo_user(user_repo)
                user_repo.delete_basket(basket_id, demo_user.id)
                flash(_("Canasta eliminada."), "success")
        except Exception as exc:
            logger.error("Error deleting basket %d: %s", basket_id, exc, exc_info=True)
            flash(_("Error al eliminar la canasta."), "error")
        return redirect(url_for("baskets"))

    @app.route("/api/articles/search")
    def api_search_articles():
        q = request.args.get("q", "")
        mode = request.args.get("mode", "fuzzy")
        limit = request.args.get("limit", 20, type=int)

        try:
            with Session(public_engine) as session:
                cat_repo = SqlAlchemyCatalogRepository(session)
                results = cat_repo.search_articles(q, limit=limit, mode=mode)
                payload = [
                    {
                        "ean": r.ean,
                        "name": r.name,
                        "brand": r.brand_name or "",
                        "category": r.category_name or "",
                    }
                    for r in results
                ]
                return jsonify(payload)
        except Exception as exc:
            logger.error(
                "API article search error (q=%r, mode=%s): %s",
                q,
                mode,
                exc,
                exc_info=True,
            )
            return jsonify([]), 500

    @app.route("/baskets/<int:basket_id>/export")
    def export_basket(basket_id: int):
        try:
            with Session(user_engine) as u_session:
                user_repo = SqlAlchemyUserRepository(u_session)
                demo_user = _get_or_create_demo_user(user_repo)
                lists = user_repo.get_user_baskets(user_id=demo_user.id)
                basket = next((b for b in lists if b.id == basket_id), None)
                if not basket:
                    flash(_("Canasta no encontrada."), "error")
                    return redirect(url_for("baskets"))

                with Session(public_engine) as p_session:
                    cat_repo = SqlAlchemyCatalogRepository(p_session)
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
                    headers={
                        "Content-Disposition": f'attachment; filename="{filename}"'
                    },
                )
        except Exception as exc:
            logger.error("Error exporting basket %d: %s", basket_id, exc, exc_info=True)
            flash(_("Error al exportar la canasta en formato YAML."), "error")
            return redirect(url_for("edit_basket", basket_id=basket_id))

    @app.route("/baskets/public/<uuid_str>/export")
    def export_public_basket(uuid_str: str):
        try:
            with Session(user_engine) as u_session:
                user_repo = SqlAlchemyUserRepository(u_session)
                basket = user_repo.get_basket_by_uuid(uuid_str)
                if not basket or not basket.is_public:
                    flash(_("Esta canasta es privada o no existe."), "error")
                    return redirect(url_for("baskets")), 404

                with Session(public_engine) as p_session:
                    cat_repo = SqlAlchemyCatalogRepository(p_session)
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
                    headers={
                        "Content-Disposition": f'attachment; filename="{filename}"'
                    },
                )
        except Exception as exc:
            logger.error(
                "Error exporting public basket %s: %s", uuid_str, exc, exc_info=True
            )
            flash(_("Error al exportar la canasta pública."), "error")
            return redirect(url_for("baskets"))

    @app.route("/baskets/import", methods=["POST"])
    def import_basket():
        try:
            content = ""
            if "yaml_file" in request.files:
                file = request.files["yaml_file"]
                if file and file.filename:
                    if not (
                        file.filename.endswith(".yaml")
                        or file.filename.endswith(".yml")
                    ):
                        flash(
                            _("Formato de archivo inválido. Debe ser .yaml o .yml"),
                            "error",
                        )
                        return redirect(url_for("baskets"))
                    content = file.read().decode("utf-8", errors="replace")

            if not content and "yaml_text" in request.form:
                content = request.form.get("yaml_text", "")

            if not content.strip():
                flash(_("No se proporcionó contenido YAML para importar."), "error")
                return redirect(url_for("baskets"))

            # Parse and validate with fail fast
            parsed = BasketYamlService.import_from_yaml(content)

            # Persist imported basket for current user
            with Session(user_engine) as u_session:
                user_repo = SqlAlchemyUserRepository(u_session)
                demo_user = _get_or_create_demo_user(user_repo)

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
                    user_id=demo_user.id,
                    name=parsed.name,
                    is_public=parsed.is_public,
                    items=items,
                )
                saved = user_repo.save_basket(new_basket)

            for w in parsed.warnings:
                flash(w, "warning")
            flash(_("Canasta importada exitosamente."), "success")
            return redirect(url_for("edit_basket", basket_id=saved.id))

        except YamlValidationError as yerr:
            logger.warning("YAML validation failure on import: %s", yerr)
            flash(str(yerr), "error")
            return redirect(url_for("baskets"))
        except Exception as exc:
            logger.error(
                "Unexpected error importing basket YAML: %s", exc, exc_info=True
            )
            flash(
                _("Ocurrió un error inesperado al procesar el archivo YAML."), "error"
            )
            return redirect(url_for("baskets"))

    @app.route("/baskets/open")
    def open_public_by_uuid():
        uuid_str = request.args.get("uuid", "").strip()
        if not uuid_str:
            flash(_("Debes ingresar un código UUID válido."), "warning")
            return redirect(url_for("baskets"))
        return redirect(url_for("view_public_basket", uuid_str=uuid_str))

    @app.route("/baskets/public/<uuid_str>")
    def view_public_basket(uuid_str: str):
        try:
            with Session(user_engine) as u_session:
                user_repo = SqlAlchemyUserRepository(u_session)
                basket = user_repo.get_basket_by_uuid(uuid_str)
                if not basket or not basket.is_public:
                    flash(_("Esta canasta es privada o no existe."), "error")
                    return render_template_string(
                        PUBLIC_LAYOUT_HEADER
                        + '<div class="card"><h2>{{ _("Canasta no disponible") }}</h2><p>{{ _("Esta canasta es privada o el enlace es incorrecto.") }}</p><a href="{{ url_for(\'baskets\') }}" class="btn">{{ _("Ir a Mis Canastas") }}</a></div>'
                        + PUBLIC_LAYOUT_FOOTER
                    ), 404

                items_data = []
                with Session(public_engine) as pub_session:
                    cat_repo = SqlAlchemyCatalogRepository(pub_session)
                    for item in basket.items:
                        card = cat_repo.get_article_by_ean(item.ean)
                        items_data.append(
                            {
                                "ean": item.ean,
                                "name": card.name if card else f"Producto {item.ean}",
                                "brand": card.brand_name if card else "",
                                "category": card.category_name if card else "",
                                "quantity": item.quantity,
                                "selected": getattr(item, "selected", True),
                                "numerator": getattr(item, "numerator", 1) or 1,
                                "denominator": getattr(item, "denominator", 1) or 1,
                            }
                        )

                return render_template_string(
                    PUBLIC_BASKET_VIEW_TEMPLATE,
                    basket=basket,
                    items_data=items_data,
                )
        except Exception as exc:
            logger.error(
                "Error viewing public basket %s: %s", uuid_str, exc, exc_info=True
            )
            flash(_("Error al cargar la canasta pública."), "error")
            return redirect(url_for("baskets"))

    @app.route("/baskets/public/<uuid_str>/clone", methods=["POST"])
    def clone_public_basket(uuid_str: str):
        try:
            with Session(user_engine) as session:
                user_repo = SqlAlchemyUserRepository(session)
                demo_user = _get_or_create_demo_user(user_repo)
                basket = user_repo.get_basket_by_uuid(uuid_str)
                if not basket or not basket.is_public:
                    flash(_("Esta canasta no está disponible para clonar."), "error")
                    return redirect(url_for("baskets")), 404

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
                    user_id=demo_user.id,
                    name=f"{basket.name} (Copia)",
                    is_public=False,
                    items=cloned_items,
                )
                saved = user_repo.save_basket(cloned_basket)
                flash(_("Canasta copiada a tus canastas guardadas."), "success")
                return redirect(url_for("edit_basket", basket_id=saved.id))
        except Exception as exc:
            logger.error(
                "Error cloning public basket %s: %s", uuid_str, exc, exc_info=True
            )
            flash(_("Error al guardar una copia de la canasta."), "error")
            return redirect(url_for("baskets"))

    @app.route("/optimize")
    def optimize():
        selected_city = request.args.get("city", "Bahía Blanca")
        selected_date_str = request.args.get("date", date.today().strftime("%Y-%m-%d"))
        eans_str = request.args.get("eans", "")
        list_id = request.args.get("list_id")
        public_uuid = request.args.get("public_uuid")

        requested_items: List[BasketItem] = []

        if public_uuid:
            try:
                with Session(user_engine) as session:
                    user_repo = SqlAlchemyUserRepository(session)
                    target_list = user_repo.get_basket_by_uuid(public_uuid)
                    if target_list and target_list.is_public:
                        requested_items = [
                            it
                            for it in target_list.items
                            if getattr(it, "selected", True) is not False
                        ]
                        eans_str = ", ".join([item.ean for item in requested_items])
            except Exception as exc:
                logger.error(
                    "Error fetching public basket for optimization: %s",
                    exc,
                    exc_info=True,
                )

        elif list_id and not eans_str:
            try:
                with Session(user_engine) as session:
                    user_repo = SqlAlchemyUserRepository(session)
                    demo_user = _get_or_create_demo_user(user_repo)
                    lists = user_repo.get_user_baskets(user_id=demo_user.id)
                    target_list = next(
                        (
                            list_obj
                            for list_obj in lists
                            if str(list_obj.id) == str(list_id)
                        ),
                        None,
                    )
                    if target_list:
                        requested_items = [
                            it
                            for it in target_list.items
                            if getattr(it, "selected", True) is not False
                        ]
                        eans_str = ", ".join([item.ean for item in requested_items])
            except Exception as exc:
                logger.error(
                    "Error fetching basket %s for optimization: %s",
                    list_id,
                    exc,
                    exc_info=True,
                )

        result = None
        if eans_str:
            try:
                target_date = date.fromisoformat(selected_date_str)
                if not requested_items:
                    ean_list = [e.strip() for e in eans_str.split(",") if e.strip()]
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

                with Session(public_engine) as session:
                    cat_repo = SqlAlchemyCatalogRepository(session)
                    price_repo = SqlAlchemyPriceRepository(session)
                    use_case = OptimizeBasketUseCase(cat_repo, price_repo)
                    result = use_case.execute(
                        selected_city, target_date, requested_items
                    )
            except Exception as exc:
                logger.error("Optimization calculation error: %s", exc, exc_info=True)
                flash(
                    _("Error al calcular los precios óptimos para la canasta."), "error"
                )

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
