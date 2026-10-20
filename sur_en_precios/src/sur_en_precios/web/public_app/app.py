import json
import logging
import re
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
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session, joinedload

from sur_en_precios.adapters.database.repositories import (
    SqlAlchemyCatalogRepository,
    SqlAlchemyPriceRepository,
    SqlAlchemyUserRepository,
)
from sur_en_precios.config import read_config
from sur_en_precios.domain.models_public import ArticleCard, Category, PublicBase, Tag
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
        .badge-warning { background: rgba(255, 183, 3, 0.25); color: var(--warning); border: 1px solid var(--warning); }
        .badge-danger { background: rgba(230, 57, 70, 0.25); color: var(--danger); border: 1px solid var(--danger); }
        .badge-info { background: rgba(72, 202, 228, 0.25); color: var(--accent); border: 1px solid var(--accent); }
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
        .ean-link { color: var(--accent); text-decoration: none; display: inline-flex; align-items: center; gap: 0.35rem; cursor: pointer; border-radius: 4px; padding: 2px 6px; transition: background 0.15s ease, color 0.15s ease; font-weight: 500; }
        .ean-link:hover { background: rgba(72, 202, 228, 0.15); text-decoration: underline; }
        .ean-link code { color: inherit; background: rgba(11, 19, 43, 0.6); padding: 2px 6px; border-radius: 4px; border: 1px solid #3a506b; font-size: 0.9em; }
        .price-dialog { background: var(--card); color: var(--text); border: 1px solid #3a506b; border-radius: 12px; padding: 1.5rem; max-width: 680px; width: 92%; box-shadow: 0 10px 40px rgba(0,0,0,0.6); margin: auto; }
        .price-dialog::backdrop { background: rgba(11, 19, 43, 0.8); backdrop-filter: blur(4px); }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; margin: 1.25rem 0; }
        .stat-card { background: #13223f; border: 1px solid #3a506b; border-radius: 8px; padding: 1rem; text-align: center; }
        .stat-card.stat-min { border-top: 4px solid var(--success); }
        .stat-card.stat-ref { border-top: 4px solid var(--warning); }
        .stat-card.stat-max { border-top: 4px solid var(--danger); }
        .stat-val { font-size: 1.5rem; font-weight: bold; margin: 0.4rem 0; }
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

        function formatCurrency(val) {
            if (val === null || val === undefined) return "-";
            const formatted = val.toLocaleString("es-AR");
            return `$${formatted} ARS`;
        }

        function openPriceStatsModal(event, ean) {
            if (event && (event.metaKey || event.ctrlKey)) {
                return; // Let browser open in new tab
            }
            if (event) {
                event.preventDefault();
            }
            const dialog = document.getElementById("price_stats_dialog");
            const content = document.getElementById("price_stats_modal_content");
            if (!dialog || !content) return;

            content.innerHTML = `
                <div style="text-align: center; padding: 2.5rem 0;">
                    <div style="font-size: 1.1rem; color: var(--accent); margin-bottom: 0.5rem;">Cargando estadísticas de precio...</div>
                    <code style="color: #a0aec0;">EAN: ${ean}</code>
                </div>
            `;
            dialog.showModal();

            fetch(`/api/articles/${encodeURIComponent(ean)}/price-stats`)
                .then(r => {
                    if (!r.ok) throw new Error("Artículo no encontrado o error en servidor");
                    return r.json();
                })
                .then(data => {
                    renderPriceStatsModal(data);
                })
                .catch(err => {
                    content.innerHTML = `
                        <div style="text-align: center; padding: 1.5rem;">
                            <h3 style="color: var(--danger); margin-top: 0;">Error al cargar datos</h3>
                            <p style="color: #a0aec0;">${err.message || 'No se pudieron recuperar las estadísticas de precio.'}</p>
                            <button type="button" class="btn btn-secondary" onclick="closePriceStatsModal()">Cerrar</button>
                        </div>
                    `;
                });
        }

        function closePriceStatsModal() {
            const dialog = document.getElementById("price_stats_dialog");
            if (dialog) dialog.close();
        }

        function renderPriceStatsModal(data) {
            const content = document.getElementById("price_stats_modal_content");
            if (!content) return;

            let pricesHtml = "";
            if (data.store_prices && data.store_prices.length > 0) {
                const rows = data.store_prices.map(st => `
                    <tr>
                        <td>
                            <strong>${st.chain_name}</strong>
                            ${st.branch_name ? `<br><small style="color: #a0aec0;">${st.branch_name}</small>` : ''}
                        </td>
                        <td>${st.city || '-'}</td>
                        <td>
                            <strong style="color: ${st.price === data.min_price ? 'var(--success)' : (st.price === data.max_price ? 'var(--danger)' : 'var(--text)')};">
                                ${formatCurrency(st.price)}
                            </strong>
                        </td>
                        <td>
                            ${st.unit_price ? `$${st.unit_price.toFixed(2)} / ${st.unit || 'u'}` : '-'}
                        </td>
                    </tr>
                `).join("");

                pricesHtml = `
                    <h4 style="margin: 1.5rem 0 0.5rem 0; color: var(--accent);">Precios por Comercio (${data.store_prices.length})</h4>
                    <div style="max-height: 220px; overflow-y: auto; border: 1px solid #3a506b; border-radius: 6px;">
                        <table style="margin-top: 0; font-size: 0.9rem;">
                            <thead>
                                <tr>
                                    <th>Comercio</th>
                                    <th>Localidad</th>
                                    <th>Precio</th>
                                    <th>Unitario</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${rows}
                            </tbody>
                        </table>
                    </div>
                `;
            } else {
                pricesHtml = `
                    <div style="background: rgba(255, 183, 3, 0.1); border-left: 4px solid var(--warning); padding: 0.75rem 1rem; border-radius: 6px; margin-top: 1rem;">
                        <span style="color: var(--warning); font-size: 0.9rem;">No se registraron precios individuales de comercios para este artículo en la fecha actual.</span>
                    </div>
                `;
            }

            content.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; border-bottom: 1px solid #3a506b; padding-bottom: 1rem;">
                    <div>
                        <h3 style="margin: 0; color: var(--accent); font-size: 1.25rem;">${data.name || data.clean_description}</h3>
                        <div style="color: #a0aec0; font-size: 0.9rem; margin-top: 0.25rem;">
                            <span>Marca: <strong>${data.brand_name || '-'}</strong></span>
                            ${data.package ? ` | <span>Envase: ${data.package}</span>` : ''}
                            ${data.category_name ? ` | <span>Categoría: ${data.category_name}</span>` : ''}
                        </div>
                        <div style="margin-top: 0.4rem;">
                            <code style="background: #0b132b; padding: 2px 6px; border-radius: 4px; color: var(--accent); border: 1px solid #3a506b;">EAN: ${data.ean}</code>
                            ${data.date ? `<small style="color: #a0aec0; margin-left: 0.75rem;">Fecha: ${data.date}</small>` : ''}
                            ${data.city ? `<span class="badge badge-info" style="margin-left: 0.5rem;">${data.city}</span>` : ''}
                        </div>
                    </div>
                    <button type="button" onclick="closePriceStatsModal()" style="background: transparent; border: none; color: #a0aec0; font-size: 1.5rem; cursor: pointer; padding: 0 0.5rem; line-height: 1;" title="Cerrar">&times;</button>
                </div>

                <div class="stats-grid">
                    <div class="stat-card stat-min">
                        <small style="color: var(--success); text-transform: uppercase; font-size: 0.75rem; font-weight: bold;">Precio Mínimo</small>
                        <div class="stat-val" style="color: var(--success);">${formatCurrency(data.min_price)}</div>
                        <small style="color: #a0aec0; font-size: 0.8rem;">${data.cheapest_store || '-'}</small>
                    </div>
                    <div class="stat-card stat-ref">
                        <small style="color: var(--warning); text-transform: uppercase; font-size: 0.75rem; font-weight: bold;">Precio Referencia</small>
                        <div class="stat-val" style="color: var(--warning);">${formatCurrency(data.reference_price)}</div>
                        <small style="color: #a0aec0; font-size: 0.8rem;">Media geométrica SEPA</small>
                    </div>
                    <div class="stat-card stat-max">
                        <small style="color: var(--danger); text-transform: uppercase; font-size: 0.75rem; font-weight: bold;">Precio Máximo</small>
                        <div class="stat-val" style="color: var(--danger);">${formatCurrency(data.max_price)}</div>
                        <small style="color: #a0aec0; font-size: 0.8rem;">${data.most_expensive_store || '-'}</small>
                    </div>
                </div>

                ${data.price_dispersion !== null && data.price_dispersion !== undefined ? `
                    <div style="background: #13223f; border: 1px solid #3a506b; border-radius: 6px; padding: 0.6rem 1rem; display: flex; justify-content: space-between; align-items: center; font-size: 0.85rem;">
                        <span>Dispersión de Precios: <strong>${(data.price_dispersion * 100).toFixed(1)}%</strong></span>
                        ${data.min_price && data.max_price && data.max_price > data.min_price ? `
                            <span style="color: var(--success); font-weight: bold;">Ahorro potencial: ${formatCurrency(data.max_price - data.min_price)}</span>
                        ` : ''}
                    </div>
                ` : ''}

                ${pricesHtml}

                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 1.5rem; border-top: 1px solid #3a506b; padding-top: 1rem;">
                    <a href="/article/${encodeURIComponent(data.ean)}" class="btn btn-sm btn-secondary" target="_blank">Ver Página Completa ↗</a>
                    <button type="button" class="btn btn-sm" onclick="closePriceStatsModal()">Cerrar</button>
                </div>
            `;
        }
    </script>
</head>
<body>
    <header>
        <h1>Sur en Precios</h1>
        <nav>
            <a href="{{ url_for('index') }}">{{ _('Buscar Productos') }}</a>
            <a href="{{ url_for('departments') }}">{{ _('Categorías') }}</a>
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
        <dialog id="price_stats_dialog" class="price-dialog" onclick="if(event.target === this) this.close();">
            <div id="price_stats_modal_content"></div>
        </dialog>
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
                        <td>
                            <a href="{{ url_for('article_detail', ean=p.ean) }}" class="ean-link" onclick="openPriceStatsModal(event, '{{ p.ean }}');" title="{{ _('Ver estadísticas de precio') }}">
                                <code>{{ p.ean }}</code> 📊
                            </a>
                        </td>
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

DEPARTMENTS_TEMPLATE = (
    PUBLIC_LAYOUT_HEADER
    + """
        <div class="card">
            <h2>{{ _('Explorar por Categoría') }}</h2>
            <p>{{ _('Navegá por los departamentos del catálogo maestro:') }}</p>
            <div class="grid" style="margin-top: 1.5rem;">
                {% for dept in departments %}
                <div class="card" style="background: #13223f; border: 1px solid #3a506b; margin-bottom: 0;">
                    <h3 style="color: var(--accent); margin-top: 0;">
                        <a href="{{ url_for('department_view', slug=dept.slug) }}" style="color: var(--accent); text-decoration: none;">
                            {{ dept.name }}
                        </a>
                    </h3>
                    <p style="color: #a0aec0; font-size: 0.9rem;">
                        {{ dept.children|length }} {{ _('subcategorías') }}
                    </p>
                    <a href="{{ url_for('department_view', slug=dept.slug) }}" class="btn btn-sm">
                        {{ _('Ver subcategorías →') }}
                    </a>
                </div>
                {% endfor %}
            </div>
        </div>
"""
    + PUBLIC_LAYOUT_FOOTER
)

DEPARTMENT_VIEW_TEMPLATE = (
    PUBLIC_LAYOUT_HEADER
    + """
        <div class="card">
            <p><a href="{{ url_for('departments') }}" style="color: var(--muted); text-decoration: none;">← {{ _('Todas las categorías') }}</a></p>
            <h2>{{ department.name }}</h2>
            <p>{{ _('Seleccioná una subcategoría para explorar artículos:') }}</p>
            <div class="grid" style="margin-top: 1.5rem;">
                {% for sub in subcategories %}
                <div class="card" style="background: #13223f; border: 1px solid #3a506b; margin-bottom: 0;">
                    <h3 style="color: var(--accent); margin-top: 0;">
                        <a href="{{ url_for('subcategory_view', slug=sub.slug) }}" style="color: var(--accent); text-decoration: none;">
                            {{ sub.name }}
                        </a>
                    </h3>
                    <a href="{{ url_for('subcategory_view', slug=sub.slug) }}" class="btn btn-sm">
                        {{ _('Ver productos →') }}
                    </a>
                </div>
                {% endfor %}
            </div>
        </div>
"""
    + PUBLIC_LAYOUT_FOOTER
)

ARTICLES_LIST_TEMPLATE = (
    PUBLIC_LAYOUT_HEADER
    + """
        <div class="card">
            <p>
                {% if back_url %}
                <a href="{{ back_url }}" style="color: var(--muted); text-decoration: none;">← {{ back_label }}</a>
                {% else %}
                <a href="{{ url_for('departments') }}" style="color: var(--muted); text-decoration: none;">← {{ _('Categorías') }}</a>
                {% endif %}
            </p>
            <h2>{{ title }}</h2>
            <p style="color: #a0aec0;">{{ subtitle }}</p>
            {% if articles %}
            <table>
                <thead>
                    <tr>
                        <th>{{ _('EAN') }}</th>
                        <th>{{ _('Producto') }}</th>
                        <th>{{ _('Marca') }}</th>
                        <th>{{ _('Envase') }}</th>
                        <th>{{ _('Etiquetas') }}</th>
                    </tr>
                </thead>
                <tbody>
                    {% for a in articles %}
                    <tr>
                        <td>
                            <a href="{{ url_for('article_detail', ean=a.ean) }}" class="ean-link" onclick="openPriceStatsModal(event, '{{ a.ean }}');" title="{{ _('Ver estadísticas de precio') }}">
                                <code>{{ a.ean }}</code> 📊
                            </a>
                        </td>
                        <td><strong>{{ a.name or a.clean_description }}</strong></td>
                        <td>{{ a.brand_name or '-' }}</td>
                        <td>{{ a.package or '-' }}</td>
                        <td>
                            {% for tag in a.tags %}
                            <a href="{{ url_for('tag_view', name=tag.name) }}" class="badge" style="background: #253355; color: var(--accent); text-decoration: none; margin-right: 4px;">
                                #{{ tag.name }}
                            </a>
                            {% endfor %}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <p style="padding: 1rem; color: #a0aec0;">{{ _('No se encontraron artículos.') }}</p>
            {% endif %}
        </div>
"""
    + PUBLIC_LAYOUT_FOOTER
)

ARTICLE_DETAIL_TEMPLATE = (
    PUBLIC_LAYOUT_HEADER
    + """
        <div class="card">
            <p>
                <a href="javascript:history.back()" style="color: var(--muted); text-decoration: none;">← {{ _('Volver') }}</a>
            </p>
            <div style="display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-start; gap: 1rem; border-bottom: 1px solid #3a506b; padding-bottom: 1.25rem;">
                <div>
                    <h2 style="margin: 0; color: var(--accent);">{{ stats.name or stats.clean_description }}</h2>
                    <p style="color: #a0aec0; margin: 0.5rem 0;">
                        <span>Marca: <strong>{{ stats.brand_name or '-' }}</strong></span>
                        {% if stats.package %} | <span>Envase: <strong>{{ stats.package }}</strong></span>{% endif %}
                        {% if stats.category_name %} | <span>Categoría: <strong>{{ stats.category_name }}</strong></span>{% endif %}
                    </p>
                    <div style="display: flex; gap: 0.5rem; align-items: center; margin-top: 0.5rem;">
                        <code style="font-size: 1.05rem; background: #0b132b; padding: 4px 8px; border-radius: 4px; border: 1px solid #3a506b; color: var(--accent);">EAN: {{ stats.ean }}</code>
                        {% if stats.date %}<span style="color: #a0aec0; font-size: 0.9rem;">Fecha: {{ stats.date }}</span>{% endif %}
                        {% if stats.city %}<span class="badge badge-info">{{ stats.city }}</span>{% endif %}
                    </div>
                </div>
                <div>
                    <a href="{{ url_for('optimize') }}?eans={{ stats.ean }}" class="btn btn-success">
                        {{ _('Ver en Optimizar Precios') }}
                    </a>
                </div>
            </div>

            <div class="stats-grid" style="margin-top: 1.5rem;">
                <div class="stat-card stat-min">
                    <small style="color: var(--success); text-transform: uppercase; font-size: 0.8rem; font-weight: bold;">{{ _('Precio Mínimo') }}</small>
                    <div class="stat-val" style="color: var(--success);">{{ stats.min_price | format_currency }}</div>
                    <small style="color: #a0aec0;">{{ stats.cheapest_store or '-' }}</small>
                </div>
                <div class="stat-card stat-ref">
                    <small style="color: var(--warning); text-transform: uppercase; font-size: 0.8rem; font-weight: bold;">{{ _('Precio de Referencia') }}</small>
                    <div class="stat-val" style="color: var(--warning);">{{ stats.reference_price | format_currency }}</div>
                    <small style="color: #a0aec0;">{{ _('Media geométrica SEPA') }}</small>
                </div>
                <div class="stat-card stat-max">
                    <small style="color: var(--danger); text-transform: uppercase; font-size: 0.8rem; font-weight: bold;">{{ _('Precio Máximo') }}</small>
                    <div class="stat-val" style="color: var(--danger);">{{ stats.max_price | format_currency }}</div>
                    <small style="color: #a0aec0;">{{ stats.most_expensive_store or '-' }}</small>
                </div>
            </div>

            {% if stats.price_dispersion is not none %}
            <div style="background: #13223f; border: 1px solid #3a506b; border-radius: 8px; padding: 1rem; margin-bottom: 1.5rem; display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 1rem;">
                <div>
                    <strong>{{ _('Dispersión de Precios:') }}</strong>
                    <span class="badge {% if stats.price_dispersion > 0.3 %}badge-danger{% elif stats.price_dispersion > 0.15 %}badge-warning{% else %}badge-lowest{% endif %}">
                        {{ "%.1f"|format(stats.price_dispersion * 100) }}%
                    </span>
                </div>
                {% if stats.min_price and stats.max_price and stats.max_price > stats.min_price %}
                <div style="color: var(--success); font-weight: bold;">
                    {{ _('Ahorro potencial:') }} {{ (stats.max_price - stats.min_price) | format_currency }}
                </div>
                {% endif %}
            </div>
            {% endif %}

            <h3>{{ _('Precios por Comercio y Sucursal') }}</h3>
            {% if stats.store_prices %}
            <table>
                <thead>
                    <tr>
                        <th>{{ _('Comercio / Sucursal') }}</th>
                        <th>{{ _('Localidad') }}</th>
                        <th>{{ _('Precio') }}</th>
                        <th>{{ _('Precio Unitario') }}</th>
                    </tr>
                </thead>
                <tbody>
                    {% for st in stats.store_prices %}
                    <tr>
                        <td>
                            <strong>{{ st.chain_name }}</strong>
                            {% if st.branch_name %}<br><small style="color: #a0aec0;">{{ st.branch_name }}</small>{% endif %}
                        </td>
                        <td>{{ st.city or '-' }}</td>
                        <td>
                            <strong style="color: {% if st.price == stats.min_price %}var(--success){% elif st.price == stats.max_price %}var(--danger){% else %}var(--text){% endif %};">
                                {{ st.price | format_currency }}
                            </strong>
                        </td>
                        <td>
                            {% if st.unit_price %}
                            ${{ "%.2f"|format(st.unit_price) }} / {{ st.unit or 'u' }}
                            {% else %}
                            -
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <p style="color: #a0aec0; padding: 1rem 0;">{{ _('No hay registros de precios de comercios para este artículo en la fecha actual.') }}</p>
            {% endif %}
        </div>
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
                        <button type="submit" name="action" value="save" class="btn btn-success">{{ _('Guardar Cambios') }}</button>
                        <button type="submit" name="action" value="optimize" class="btn">{{ _('Optimizar Precios') }}</button>
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
                        {{ _('Define las cantidades y ponderaciones fraccionarias para el cálculo de la canasta. Desmarca un artículo para excluirlo temporalmente de la optimización.') }}
                    </p>

                    <div style="overflow-x: auto;">
                        <table id="basket_items_table">
                            <thead>
                                <tr>
                                    <th style="width: 40px; text-align: center;">{{ _('Activo') }}</th>
                                    <th>{{ _('Producto') }}</th>
                                    <th style="width: 75px;">{{ _('Cant. (Q)') }}</th>
                                    <th style="width: 95px;">{{ _('Frac. (N/D)') }}</th>
                                    <th style="width: 80px; text-align: center;">{{ _('Pond. (W)') }}</th>
                                    <th style="width: 50px;">{{ _('Acción') }}</th>
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
                                        <input type="number" name="item_quantity_{{ item.ean }}" value="{{ item.quantity }}" min="1" required style="width: 65px; padding: 0.4rem;" oninput="updateRowWeight('{{ item.ean }}')">
                                    </td>
                                    <td>
                                        <div style="display: flex; align-items: center; gap: 4px;">
                                            <input type="number" name="item_numerator_{{ item.ean }}" value="{{ item.numerator }}" min="1" required style="width: 40px; padding: 0.4rem;" oninput="updateRowWeight('{{ item.ean }}')">
                                            <span>/</span>
                                            <input type="number" name="item_denominator_{{ item.ean }}" value="{{ item.denominator }}" min="1" required style="width: 40px; padding: 0.4rem;" oninput="updateRowWeight('{{ item.ean }}')">
                                        </div>
                                    </td>
                                    <td style="text-align: center;">
                                        <strong id="weight_{{ item.ean }}" style="color: var(--accent); font-size: 0.95rem;">
                                            {{ "%.2f"|format(item.quantity * item.numerator / item.denominator) if item.denominator else item.quantity }}
                                        </strong>
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
                        {{ _('No hay artículos en la canasta. Utiliza el buscador o explorador de categorías para agregar productos.') }}
                    </div>
                </div>

                <!-- Right Column: Product Search & Category Browser -->
                <div class="card">
                    <h3>{{ _('Buscador de Artículos') }}</h3>
                    <!-- Tab Switcher -->
                    <div style="display: flex; gap: 0.5rem; margin-bottom: 1rem; border-bottom: 1px solid #3a506b; padding-bottom: 0.75rem;">
                        <button type="button" id="tab_search_btn" class="btn btn-sm btn-success" onclick="switchRightPanelTab('search')">
                            🔍 {{ _('Búsqueda de Texto') }}
                        </button>
                        <button type="button" id="tab_categories_btn" class="btn btn-sm btn-secondary" onclick="switchRightPanelTab('categories')">
                            📂 {{ _('Explorar Categorías') }}
                        </button>
                    </div>

                    <!-- Panel 1: Text Search -->
                    <div id="panel_text_search">
                        <p style="font-size: 0.85rem; color: #a0aec0; margin-top: 0;">
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
                    </div>

                    <!-- Panel 2: Two-Level Category Browser -->
                    <div id="panel_category_browse" style="display: none;">
                        <p style="font-size: 0.85rem; color: #a0aec0; margin-top: 0;">
                            {{ _('Explora el catálogo por Departamento y Subcategoría para agregar artículos masivamente:') }}
                        </p>
                        <div style="display: flex; flex-direction: column; gap: 0.75rem;">
                            <div>
                                <label style="font-size: 0.85rem; font-weight: bold; color: var(--accent);">{{ _('1. Departamento:') }}</label>
                                <select id="dept_select" onchange="onDepartmentSelect()" style="margin-top: 0.25rem;">
                                    <option value="">-- {{ _('Selecciona un Departamento') }} --</option>
                                    {% for dept in departments %}
                                    <option value="{{ dept.slug }}">{{ dept.name }} ({{ dept.children|length }} subcat.)</option>
                                    {% endfor %}
                                </select>
                            </div>
                            <div>
                                <label style="font-size: 0.85rem; font-weight: bold; color: var(--accent);">{{ _('2. Subcategoría:') }}</label>
                                <select id="subcat_select" onchange="onSubcategorySelect()" disabled style="margin-top: 0.25rem;">
                                    <option value="">-- {{ _('Selecciona primero un departamento') }} --</option>
                                </select>
                            </div>
                        </div>
                    </div>

                    <!-- Results Bar -->
                    <div id="search_actions_bar" style="display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; margin-top: 1rem; min-height: 32px; gap: 0.5rem;">
                        <span id="search_results_count" style="font-size: 0.85rem; color: #a0aec0;"></span>
                        <button type="button" id="btn_add_all_found" class="btn btn-sm btn-secondary" onclick="addAllFoundArticles()" disabled style="opacity: 0.6; cursor: not-allowed;">
                            + {{ _('Agregar todos los artículos encontrados') }}
                        </button>
                    </div>

                    <!-- Results Box -->
                    <div class="search-results-box" id="search_results_container">
                        <div id="search_placeholder" style="text-align: center; padding: 2rem 0; color: #a0aec0;">
                            {{ _('Escribe un término o selecciona una categoría para ver productos.') }}
                        </div>
                    </div>
                </div>
            </div>
        </form>

        <script>
            let eanSet = new Set({{ eans_list | tojson }});
            let lastSearchResults = [];
            const categoriesData = {{ departments_json | safe }};

            function updateRowWeight(ean) {
                const qInput = document.querySelector('input[name="item_quantity_' + ean + '"]');
                const nInput = document.querySelector('input[name="item_numerator_' + ean + '"]');
                const dInput = document.querySelector('input[name="item_denominator_' + ean + '"]');
                const wSpan = document.getElementById('weight_' + ean);
                if (qInput && nInput && dInput && wSpan) {
                    const q = parseFloat(qInput.value || 1);
                    const n = parseFloat(nInput.value || 1);
                    const d = parseFloat(dInput.value || 1) || 1;
                    wSpan.innerText = (q * n / d).toFixed(2);
                }
            }

            function switchRightPanelTab(tab) {
                const searchPanel = document.getElementById('panel_text_search');
                const catPanel = document.getElementById('panel_category_browse');
                const btnSearch = document.getElementById('tab_search_btn');
                const btnCat = document.getElementById('tab_categories_btn');

                if (tab === 'search') {
                    searchPanel.style.display = 'block';
                    catPanel.style.display = 'none';
                    btnSearch.className = 'btn btn-sm btn-success';
                    btnCat.className = 'btn btn-sm btn-secondary';
                } else {
                    searchPanel.style.display = 'none';
                    catPanel.style.display = 'block';
                    btnSearch.className = 'btn btn-sm btn-secondary';
                    btnCat.className = 'btn btn-sm btn-success';
                }
            }

            function onDepartmentSelect() {
                const deptSlug = document.getElementById('dept_select').value;
                const subcatSelect = document.getElementById('subcat_select');
                subcatSelect.innerHTML = '<option value="">-- {{ _("Selecciona una Subcategoría") }} --</option>';

                if (!deptSlug) {
                    subcatSelect.disabled = true;
                    return;
                }

                const deptObj = categoriesData.find(d => d.slug === deptSlug);
                if (deptObj && deptObj.children && deptObj.children.length > 0) {
                    deptObj.children.forEach(sub => {
                        const opt = document.createElement('option');
                        opt.value = sub.slug;
                        opt.innerText = sub.name;
                        subcatSelect.appendChild(opt);
                    });
                    subcatSelect.disabled = false;
                } else {
                    subcatSelect.disabled = true;
                }
            }

            function onSubcategorySelect() {
                const subcatSlug = document.getElementById('subcat_select').value;
                if (!subcatSlug) return;

                const container = document.getElementById('search_results_container');
                const btnAll = document.getElementById('btn_add_all_found');
                const countSpan = document.getElementById('search_results_count');

                lastSearchResults = [];
                if (btnAll) {
                    btnAll.disabled = true;
                    btnAll.className = 'btn btn-sm btn-secondary';
                    btnAll.style.opacity = '0.6';
                    btnAll.style.cursor = 'not-allowed';
                }
                if (countSpan) {
                    countSpan.innerText = '';
                }

                container.innerHTML = '<div style="text-align: center; padding: 2rem 0; color: var(--accent);">Cargando artículos de la subcategoría...</div>';

                fetch('/api/categories/' + encodeURIComponent(subcatSlug) + '/articles')
                    .then(r => r.json())
                    .then(data => {
                        renderArticleResults(data);
                    })
                    .catch(err => {
                        container.innerHTML = '<div style="text-align: center; padding: 2rem 0; color: var(--danger);">Error al cargar artículos de la subcategoría.</div>';
                    });
            }

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

            function addItemToBasket(ean, name, brand, category, incrementIfExists = true) {
                if (eanSet.has(ean)) {
                    if (incrementIfExists) {
                        const qtyInput = document.querySelector('input[name="item_quantity_' + ean + '"]');
                        if (qtyInput) {
                            qtyInput.value = parseInt(qtyInput.value || 1) + 1;
                            qtyInput.style.borderColor = 'var(--accent)';
                            setTimeout(() => qtyInput.style.borderColor = '#3a506b', 1000);
                            updateRowWeight(ean);
                        }
                    }
                    const chk = document.querySelector('input[name="item_selected_' + ean + '"]');
                    if (chk) {
                        chk.checked = true;
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
                        <input type="number" name="item_quantity_${ean}" value="1" min="1" required style="width: 65px; padding: 0.4rem;" oninput="updateRowWeight('${ean}')">
                    </td>
                    <td>
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <input type="number" name="item_numerator_${ean}" value="1" min="1" required style="width: 40px; padding: 0.4rem;" oninput="updateRowWeight('${ean}')">
                            <span>/</span>
                            <input type="number" name="item_denominator_${ean}" value="1" min="1" required style="width: 40px; padding: 0.4rem;" oninput="updateRowWeight('${ean}')">
                        </div>
                    </td>
                    <td style="text-align: center;">
                        <strong id="weight_${ean}" style="color: var(--accent); font-size: 0.95rem;">1.00</strong>
                    </td>
                    <td>
                        <button type="button" class="btn btn-danger btn-sm" onclick="removeItem('${ean}')">&times;</button>
                    </td>
                `;
                tbody.appendChild(tr);
            }

            function addAllFoundArticles() {
                if (!lastSearchResults || lastSearchResults.length === 0) return;
                lastSearchResults.forEach(item => {
                    addItemToBasket(item.ean, item.name || '', item.brand || '', item.category || '', false);
                });
                const btn = document.getElementById('btn_add_all_found');
                if (btn) {
                    const origText = btn.innerText;
                    btn.innerText = "¡Agregados!";
                    btn.classList.remove('btn-secondary');
                    btn.classList.add('btn-success');
                    setTimeout(() => {
                        btn.innerText = origText;
                    }, 1500);
                }
            }
            const selectAllFoundArticles = addAllFoundArticles;

            function renderArticleResults(data) {
                const container = document.getElementById('search_results_container');
                const btnAll = document.getElementById('btn_add_all_found');
                const countSpan = document.getElementById('search_results_count');

                if (!data || data.length === 0) {
                    container.innerHTML = '<div style="text-align: center; padding: 2rem 0; color: #a0aec0;">No se encontraron artículos.</div>';
                    return;
                }
                lastSearchResults = data;
                if (btnAll) {
                    btnAll.disabled = false;
                    btnAll.className = 'btn btn-sm btn-success';
                    btnAll.style.opacity = '1';
                    btnAll.style.cursor = 'pointer';
                }
                if (countSpan) {
                    countSpan.innerText = data.length + ' ' + (data.length === 1 ? 'artículo disponible' : 'artículos disponibles');
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
                                <span>${item.brand || '-'}</span> | <span>${item.category || '-'}</span> | <a href="/article/${encodeURIComponent(item.ean)}" class="ean-link" onclick="openPriceStatsModal(event, '${item.ean}')" style="padding: 0;"><code>${item.ean}</code> 📊</a>
                            </div>
                        </div>
                        <div>
                            <button type="button" class="btn btn-sm btn-success" onclick="addItemToBasket('${item.ean}', '${safeName}', '${safeBrand}', '${safeCat}')">+ Agregar</button>
                        </div>
                    `;
                    container.appendChild(card);
                });
            }

            function searchArticles() {
                const q = document.getElementById('search_input').value.trim();
                if (!q) return;

                const mode = document.getElementById('mode_exact').checked ? 'exact' : 'fuzzy';
                const container = document.getElementById('search_results_container');
                const btnAll = document.getElementById('btn_add_all_found');
                const countSpan = document.getElementById('search_results_count');

                lastSearchResults = [];
                if (btnAll) {
                    btnAll.disabled = true;
                    btnAll.className = 'btn btn-sm btn-secondary';
                    btnAll.style.opacity = '0.6';
                    btnAll.style.cursor = 'not-allowed';
                }
                if (countSpan) {
                    countSpan.innerText = '';
                }

                container.innerHTML = '<div style="text-align: center; padding: 2rem 0; color: var(--accent);">Buscando productos...</div>';

                fetch('{{ url_for("api_search_articles") }}?q=' + encodeURIComponent(q) + '&mode=' + mode)
                    .then(r => r.json())
                    .then(data => {
                        renderArticleResults(data);
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
                {% if list_id %}
                <input type="hidden" name="list_id" value="{{ list_id }}">
                {% endif %}
                {% if public_uuid %}
                <input type="hidden" name="public_uuid" value="{{ public_uuid }}">
                {% endif %}

                {% if user_baskets %}
                <div class="form-group">
                    <label><strong>{{ _('Cargar Canasta Guardada') }}</strong></label>
                    <select id="basket_selector" onchange="if(this.value){ const cityEl = document.querySelector('select[name=city]'); const dateEl = document.querySelector('input[name=date]'); const cityParam = cityEl ? ('&city=' + encodeURIComponent(cityEl.value)) : ''; const dateParam = dateEl ? ('&date=' + encodeURIComponent(dateEl.value)) : ''; window.location.href='{{ url_for('optimize') }}?list_id=' + this.value + cityParam + dateParam; }" style="margin-top: 0.25rem;">
                        <option value="">-- {{ _('Seleccionar una canasta guardada...') }} --</option>
                        {% for ub in user_baskets %}
                        <option value="{{ ub.id }}" {% if list_id and list_id|string == ub.id|string %}selected{% endif %}>
                            {{ ub.name }} ({{ ub.items|length }} {{ _('artículos') }})
                        </option>
                        {% endfor %}
                    </select>
                </div>
                {% endif %}

                <div class="grid">
                    <div class="form-group">
                        <label><strong>{{ _('Ciudad') }}</strong></label>
                        <select name="city" required>
                            {% for c in cities %}
                            <option value="{{ c }}" {% if c == selected_city %}selected{% endif %}>{{ c }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div class="form-group">
                        <label><strong>{{ _('Fecha') }}</strong></label>
                        <input type="date" name="date" value="{{ selected_date_str }}" required>
                    </div>
                </div>
                <div class="form-group">
                    <label><strong>{{ _('Códigos EAN de la Canasta') }}</strong></label>
                    <input type="text" name="eans" value="{{ eans_str }}" placeholder="{{ _('Códigos EAN separados por coma o espacio') }}" required>
                </div>
                <button type="submit">{{ _('Calcular') }}</button>
            </form>
        </div>

        {% if result %}
        {% if not result.item_by_item_optimal and not result.complete_stores and not result.partial_stores %}
        <div class="card" style="border-left: 6px solid var(--warning);">
            <h3 style="color: var(--warning); margin-top: 0;">{{ _('Sin resultados para esta selección') }}</h3>
            <p>{{ _('No se encontraron precios en comercios de') }} <strong>{{ selected_city }}</strong> {{ _('para la fecha') }} <strong>{{ selected_date_str }}</strong> {{ _('para los artículos consultados.') }}</p>
            {% if unpriced_items %}
            <p style="color: #a0aec0; font-size: 0.9rem;">{{ _('Artículos de la canasta sin disponibilidad registrada en esta localidad:') }}</p>
            <table>
                <thead>
                    <tr>
                        <th>{{ _('Código EAN') }}</th>
                        <th>{{ _('Producto') }}</th>
                        <th>{{ _('Marca') }}</th>
                    </tr>
                </thead>
                <tbody>
                    {% for item in unpriced_items %}
                    <tr>
                        <td><code>{{ item.ean }}</code></td>
                        <td>{{ item.name }}</td>
                        <td>{{ item.brand or '-' }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% endif %}
            <p style="margin-top: 1rem; color: #a0aec0; font-size: 0.85rem;">
                {{ _('Sugerencia: Prueba seleccionando otra ciudad de la región o consultando artículos con precios en el catálogo.') }}
            </p>
        </div>
        {% else %}
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1.5rem; margin-bottom: 2rem;">
            {% if result.best_single_store %}
            <div class="card" style="border-left: 6px solid var(--success); margin-bottom: 0;">
                <span class="badge badge-lowest" style="margin-bottom: 0.5rem;">{{ _('Comercio Único') }}</span>
                <h2>{{ result.best_single_store.store.chain_name }} — {{ result.best_single_store.store.store_name }}</h2>
                <p style="font-size: 1.8rem; font-weight: bold; color: var(--success); margin: 0.5rem 0;">
                    {{ result.best_single_store.total_price | format_currency }}
                </p>
                <small style="color: #a0aec0;">{{ _('Costo total comprando todos los artículos en un solo local.') }}</small>
            </div>
            {% endif %}

            {% if result.multi_store_total_price %}
            <div class="card" style="border-left: 6px solid var(--accent); margin-bottom: 0;">
                <span class="badge badge-info" style="margin-bottom: 0.5rem;">{{ _('Multi-Comercio Óptimo') }}</span>
                <h2>{{ _('Combinación de Precios Mínimos') }}</h2>
                <p style="font-size: 1.8rem; font-weight: bold; color: var(--accent); margin: 0.5rem 0;">
                    {{ result.multi_store_total_price | format_currency }}
                </p>
                {% if result.best_single_store and result.best_single_store.total_price > result.multi_store_total_price %}
                <small style="color: var(--success); font-weight: bold;">
                    Ahorro de {{ (result.best_single_store.total_price - result.multi_store_total_price) | format_currency }}
                    ({{ "%.1f"|format(((result.best_single_store.total_price - result.multi_store_total_price) / result.best_single_store.total_price) * 100) }}%)
                    dividiendo compras entre comercios.
                </small>
                {% else %}
                <small style="color: #a0aec0;">{{ _('Costo comprando cada producto en su punto de venta más barato.') }}</small>
                {% endif %}
            </div>
            {% endif %}
        </div>

        {% if result.item_by_item_optimal %}
        <div class="card">
            <h2>{{ _('Precios, Asignación Óptima y Dispersión por Artículo') }}</h2>
            <p style="color: #a0aec0; font-size: 0.9rem;">
                {{ _('Muestra el precio mínimo, precio de referencia (media geométrica), precio máximo y porcentaje de dispersión entre comercios de la ciudad.') }}
            </p>
            <div style="overflow-x: auto;">
                <table>
                    <thead>
                        <tr>
                            <th>{{ _('Producto') }}</th>
                            <th style="text-align: center;">{{ _('Ponderador') }}</th>
                            <th>{{ _('Precio Mínimo') }}</th>
                            <th>{{ _('Precio Referencia') }}</th>
                            <th>{{ _('Precio Máximo') }}</th>
                            <th style="text-align: center;">{{ _('Dispersión') }}</th>
                            <th>{{ _('Precio Unitario') }}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for opt in result.item_by_item_optimal %}
                        <tr>
                            <td>
                                <div><strong>{{ opt.product.name }}</strong></div>
                                <div style="font-size: 0.8rem; color: #a0aec0; margin-top: 2px;">
                                    <span>{{ opt.product.brand_name or '-' }}</span> | <code>{{ opt.product.ean }}</code>
                                </div>
                            </td>
                            <td style="text-align: center;">
                                <code>{{ opt.quantity }} × {{ opt.numerator }}/{{ opt.denominator }}</code>
                            </td>
                            <td>
                                <strong style="color: var(--success);">{{ opt.price | format_currency }}</strong>
                                <br><small style="color: #a0aec0;">{{ opt.cheapest_store.chain_name }} ({{ opt.cheapest_store.store_name }})</small>
                            </td>
                            <td>
                                {% if opt.reference_price %}
                                <span>{{ opt.reference_price | format_currency }}</span>
                                {% else %}
                                <span style="color: #a0aec0;">-</span>
                                {% endif %}
                            </td>
                            <td>
                                {% if opt.max_price %}
                                <span style="color: var(--danger);">{{ opt.max_price | format_currency }}</span>
                                {% else %}
                                <span style="color: #a0aec0;">-</span>
                                {% endif %}
                            </td>
                            <td style="text-align: center;">
                                {% if opt.price_dispersion is not none %}
                                    <span class="badge {% if opt.price_dispersion > 30 %}badge-danger{% elif opt.price_dispersion > 15 %}badge-warning{% else %}badge-lowest{% endif %}">
                                        {{ opt.price_dispersion }}%
                                    </span>
                                    {% if opt.max_price and opt.min_price and opt.max_price > opt.min_price %}
                                    <br><small style="color: #a0aec0;">+{{ (opt.max_price - opt.min_price) | format_currency }}</small>
                                    {% endif %}
                                {% else %}
                                    <span style="color: #a0aec0;">-</span>
                                {% endif %}
                            </td>
                            <td>
                                {% if opt.unit_price and opt.unit %}
                                <strong>${{ "%.2f"|format(opt.unit_price) }} / {{ opt.unit }}</strong>
                                {% else %}
                                <span style="color: #a0aec0;">-</span>
                                {% endif %}
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        {% endif %}

        {% if unpriced_items %}
        <div class="card" style="border-left: 6px solid var(--warning);">
            <h3 style="color: var(--warning); margin-top: 0;">{{ _('Artículos sin disponibilidad en esta localidad') }} ({{ unpriced_items|length }})</h3>
            <p style="color: #a0aec0; font-size: 0.9rem;">
                {{ _('Los siguientes artículos de la canasta no tienen precios registrados en comercios de') }} <strong>{{ selected_city }}</strong> {{ _('para el') }} <strong>{{ selected_date_str }}</strong>:
            </p>
            <table>
                <thead>
                    <tr>
                        <th>{{ _('Código EAN') }}</th>
                        <th>{{ _('Producto') }}</th>
                        <th>{{ _('Marca') }}</th>
                    </tr>
                </thead>
                <tbody>
                    {% for item in unpriced_items %}
                    <tr>
                        <td><code>{{ item.ean }}</code></td>
                        <td>{{ item.name }}</td>
                        <td>{{ item.brand or '-' }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}

        {% if result.suggested_substitutions %}
        <div class="card" style="border-left: 6px solid var(--warning);">
            <h2>{{ _('Sugerencias de Ahorro: Alternativas Equivalentes') }}</h2>
            <p>{{ _('Productos de la misma categoría a menor precio unitario o monto total:') }}</p>
            <table>
                <thead>
                    <tr>
                        <th>{{ _('Alternativa Sugerida') }}</th>
                        <th>{{ _('Comercio') }}</th>
                        <th>{{ _('Precio Alternativa') }}</th>
                        <th>{{ _('Ahorro Estimado') }}</th>
                    </tr>
                </thead>
                <tbody>
                    {% for sub in result.suggested_substitutions %}
                    <tr>
                        <td>
                            <strong>{{ sub.product.name }}</strong>
                            {% if sub.unit_price and sub.unit %}
                            <br><small style="color: var(--muted);">${{ sub.unit_price }} / {{ sub.unit }}</small>
                            {% endif %}
                        </td>
                        <td>{{ sub.cheapest_store.chain_name }} ({{ sub.cheapest_store.store_name }})</td>
                        <td><strong>{{ sub.price | format_currency }}</strong></td>
                        <td>
                            <span class="badge badge-lowest">
                                -{{ sub.savings_amount | format_currency }} ({{ sub.savings_percent }}%)
                            </span>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}

        {% if result.complete_stores %}
        <div class="card">
            <h2>{{ _('Matriz de Precios por Comercio (Disponibilidad 100%%)') }}</h2>
            <p>{{ _('Precios expresados en Pesos Argentinos (ARS) sin centavos para todos los comercios que disponen de la canasta completa:') }}</p>
            <table>
                <thead>
                    <tr>
                        <th>{{ _('Comercio / Sucursal') }}</th>
                        <th>{{ _('Total Canasta Ponderada') }}</th>
                        <th>{{ _('Cobertura') }}</th>
                    </tr>
                </thead>
                <tbody>
                    {% for st in result.complete_stores %}
                    <tr>
                        <td><strong>{{ st.store.chain_name }}</strong> — {{ st.store.store_name }}</td>
                        <td><strong>{{ st.total_price | format_currency }}</strong></td>
                        <td><span class="badge badge-lowest">{{ _('100%% Cobertura') }}</span></td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}

        {% if result.partial_stores %}
        <div class="card">
            <h2>{{ _('Comercios con Disponibilidad Parcial') }}</h2>
            <p style="color: #a0aec0; font-size: 0.9rem;">
                {{ _('Comercios que cuentan con una parte de los artículos solicitados:') }}
            </p>
            <table>
                <thead>
                    <tr>
                        <th>{{ _('Comercio / Sucursal') }}</th>
                        <th>{{ _('Subtotal Disponible') }}</th>
                        <th>{{ _('Artículos Disponibles') }}</th>
                    </tr>
                </thead>
                <tbody>
                    {% for st in result.partial_stores %}
                    <tr>
                        <td>{{ st.store.chain_name }} — {{ st.store.store_name }}</td>
                        <td>{{ st.total_price | format_currency }}</td>
                        <td>
                            <span class="badge badge-warning">
                                {{ st.matched_items_count }} / {{ st.requested_items_count }} {{ _('artículos') }}
                            </span>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}
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


def init_user_db(engine: Engine) -> None:
    """Initializes user database tables and ensures schema migrations for SQLite."""
    UserBase.metadata.create_all(engine)
    with engine.begin() as conn:
        try:
            res = conn.exec_driver_sql("PRAGMA table_info(basket_items)").fetchall()
            existing_cols = {row[1] for row in res}
            if existing_cols:
                if "selected" not in existing_cols:
                    conn.exec_driver_sql(
                        "ALTER TABLE basket_items ADD COLUMN selected BOOLEAN NOT NULL DEFAULT 1"
                    )
                if "numerator" not in existing_cols:
                    conn.exec_driver_sql(
                        "ALTER TABLE basket_items ADD COLUMN numerator INTEGER NOT NULL DEFAULT 1"
                    )
                if "denominator" not in existing_cols:
                    conn.exec_driver_sql(
                        "ALTER TABLE basket_items ADD COLUMN denominator INTEGER NOT NULL DEFAULT 1"
                    )
        except Exception as exc:
            logger.warning("Could not verify or migrate basket_items schema: %s", exc)

        try:
            res = conn.exec_driver_sql("PRAGMA table_info(baskets)").fetchall()
            existing_cols = {row[1] for row in res}
            if existing_cols:
                if "is_public" not in existing_cols:
                    conn.exec_driver_sql(
                        "ALTER TABLE baskets ADD COLUMN is_public BOOLEAN NOT NULL DEFAULT 0"
                    )
                if "uuid" not in existing_cols:
                    conn.exec_driver_sql(
                        "ALTER TABLE baskets ADD COLUMN uuid VARCHAR(36)"
                    )
        except Exception as exc:
            logger.warning("Could not verify or migrate baskets schema: %s", exc)


def create_public_app(workdir: Path | None = None) -> Flask:
    """Factory creating Flask public web application."""
    config = read_config(workdir_override=workdir, should_create_override=True)
    public_db_path = config.get_public_db_path()
    user_db_path = config.get_user_db_path()

    public_engine = create_engine(f"sqlite:///{public_db_path}")
    PublicBase.metadata.create_all(public_engine)

    user_engine = create_engine(f"sqlite:///{user_db_path}")
    init_user_db(user_engine)

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
                logger.error("Error searching in index: %s", exc)
                flash(_("Ocurrió un error al realizar la búsqueda."), "error")
        return render_template_string(INDEX_TEMPLATE, query=query, products=products)

    @app.route("/departments")
    def departments():
        try:
            with Session(public_engine) as session:
                cat_repo = SqlAlchemyCatalogRepository(session)
                depts = cat_repo.get_departments()
                return render_template_string(DEPARTMENTS_TEMPLATE, departments=depts)
        except Exception as exc:
            logger.error("Error loading departments: %s", exc)
            flash(_("Error al cargar las categorías."), "error")
            return render_template_string(DEPARTMENTS_TEMPLATE, departments=[])

    @app.route("/department/<slug>")
    def department_view(slug: str):
        try:
            with Session(public_engine) as session:
                cat_repo = SqlAlchemyCatalogRepository(session)
                dept = session.execute(
                    select(Category).where(Category.slug == slug, Category.level == 1)
                ).scalars().first()
                if not dept:
                    flash(_("Departamento no encontrado."), "error")
                    return redirect(url_for("departments"))
                subcategories = cat_repo.get_subcategories(slug)
                return render_template_string(
                    DEPARTMENT_VIEW_TEMPLATE,
                    department=dept,
                    subcategories=subcategories,
                )
        except Exception as exc:
            logger.error("Error loading department %s: %s", slug, exc)
            flash(_("Error al cargar el departamento."), "error")
            return redirect(url_for("departments"))

    @app.route("/subcategory/<slug>")
    def subcategory_view(slug: str):
        try:
            with Session(public_engine) as session:
                cat_repo = SqlAlchemyCatalogRepository(session)
                sub = session.execute(
                    select(Category)
                    .where(Category.slug == slug, Category.level == 2)
                    .options(joinedload(Category.parent))
                ).scalars().first()
                if not sub:
                    flash(_("Subcategoría no encontrada."), "error")
                    return redirect(url_for("departments"))
                articles = cat_repo.get_articles_by_subcategory(slug, limit=100)
                back_url = (
                    url_for("department_view", slug=sub.parent.slug)
                    if sub.parent
                    else url_for("departments")
                )
                back_label = sub.parent.name if sub.parent else _("Categorías")
                return render_template_string(
                    ARTICLES_LIST_TEMPLATE,
                    title=f"{sub.name}",
                    subtitle=f"{sub.parent.name if sub.parent else ''} — {len(articles)} artículos disponibles",
                    articles=articles,
                    back_url=back_url,
                    back_label=back_label,
                )
        except Exception as exc:
            logger.error("Error loading subcategory %s: %s", slug, exc)
            flash(_("Error al cargar la subcategoría."), "error")
            return redirect(url_for("departments"))

    @app.route("/tag/<name>")
    def tag_view(name: str):
        try:
            with Session(public_engine) as session:
                cat_repo = SqlAlchemyCatalogRepository(session)
                articles = cat_repo.get_articles_by_tag(name, limit=100)
                return render_template_string(
                    ARTICLES_LIST_TEMPLATE,
                    title=f"Etiqueta #{name}",
                    subtitle=f"{len(articles)} artículos asociados",
                    articles=articles,
                    back_url=url_for("index"),
                    back_label=_("Buscar Productos"),
                )
        except Exception as exc:
            logger.error("Error loading tag %s: %s", name, exc)
            flash(_("Error al cargar los artículos por etiqueta."), "error")
            return redirect(url_for("index"))

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
            logger.error("Error loading baskets: %s", exc)
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
            logger.error("Error creating new basket: %s", exc)
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
            logger.error("Error creating basket from form: %s", exc)
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
                    departments = cat_repo.get_departments()
                    departments_data = [
                        {
                            "name": d.name,
                            "slug": d.slug,
                            "children": [
                                {"name": c.name, "slug": c.slug}
                                for c in (d.children or [])
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
                                "category": getattr(card, "category_name", "") if card else "",
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
                    departments=departments_data,
                    departments_json=json.dumps(departments_data),
                )
        except Exception as exc:
            logger.error("Error loading basket editor: %s", exc)
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

                action = request.form.get("action", "save")
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
                if action == "optimize":
                    return redirect(url_for("optimize", list_id=basket.id))

                flash(_("Canasta guardada exitosamente."), "success")
                return redirect(url_for("edit_basket", basket_id=basket.id))
        except Exception as exc:
            logger.error("Error saving basket %d: %s", basket_id, exc)
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
            logger.error("Error deleting basket %d: %s", basket_id, exc)
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
                        "brand": getattr(r, "brand_name", None) or "",
                        "category": getattr(r, "category_name", None) or "",
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
            )
            return jsonify([]), 500

    @app.route("/api/categories/<slug>/articles")
    def api_category_articles(slug: str):
        limit = request.args.get("limit", 150, type=int)
        try:
            with Session(public_engine) as session:
                cat_repo = SqlAlchemyCatalogRepository(session)
                articles = cat_repo.get_articles_by_subcategory(slug, limit=limit)
                payload = [
                    {
                        "ean": r.ean,
                        "name": r.name,
                        "brand": getattr(r, "brand_name", None) or "",
                        "category": getattr(r, "category_name", None) or "",
                    }
                    for r in articles
                ]
                return jsonify(payload)
        except Exception as exc:
            logger.error("API category articles error (slug=%s): %s", slug, exc)
            return jsonify([]), 500

    @app.route("/api/articles/<ean>/price-stats")
    def api_article_price_stats(ean: str):
        city = request.args.get("city")
        date_str = request.args.get("date")
        target_date = date.fromisoformat(date_str) if date_str else None

        try:
            with Session(public_engine) as session:
                price_repo = SqlAlchemyPriceRepository(session)
                stats = price_repo.get_article_price_stats(
                    ean=ean, city=city, price_date=target_date
                )
                if not stats:
                    return jsonify({"error": "Artículo no encontrado"}), 404

                return jsonify(
                    {
                        "ean": stats.ean,
                        "name": stats.name,
                        "clean_description": stats.clean_description,
                        "brand_name": stats.brand_name,
                        "package": stats.package,
                        "category_name": stats.category_name,
                        "date": stats.date.isoformat() if stats.date else None,
                        "city": stats.city,
                        "min_price": stats.min_price,
                        "max_price": stats.max_price,
                        "reference_price": stats.reference_price,
                        "price_dispersion": stats.price_dispersion,
                        "cheapest_store": stats.cheapest_store,
                        "most_expensive_store": stats.most_expensive_store,
                        "stores_count": stats.stores_count,
                        "store_prices": [
                            {
                                "chain_name": st.chain_name,
                                "branch_name": st.branch_name,
                                "city": st.city,
                                "price": st.price,
                                "unit_price": st.unit_price,
                                "unit": st.unit,
                                "date": st.date.isoformat() if st.date else None,
                            }
                            for st in stats.store_prices
                        ],
                    }
                )
        except Exception as exc:
            logger.error("API article price stats error (ean=%s): %s", ean, exc)
            return jsonify({"error": "Error interno del servidor"}), 500

    @app.route("/article/<ean>")
    def article_detail(ean: str):
        city = request.args.get("city")
        date_str = request.args.get("date")
        target_date = date.fromisoformat(date_str) if date_str else None

        try:
            with Session(public_engine) as session:
                price_repo = SqlAlchemyPriceRepository(session)
                stats = price_repo.get_article_price_stats(
                    ean=ean, city=city, price_date=target_date
                )
                if not stats:
                    flash(_("Artículo no encontrado."), "error")
                    return redirect(url_for("index"))

                return render_template_string(
                    ARTICLE_DETAIL_TEMPLATE,
                    stats=stats,
                )
        except Exception as exc:
            logger.error("Error loading article detail for ean %s: %s", ean, exc)
            flash(_("Error al cargar los datos del artículo."), "error")
            return redirect(url_for("index"))

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
            logger.error("Error exporting basket %d: %s", basket_id, exc)
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
            logger.error("Error exporting public basket %s: %s", uuid_str, exc)
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
            logger.error("Unexpected error importing basket YAML: %s", exc)
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
                                "brand": getattr(card, "brand_name", "") if card else "",
                                "category": getattr(card, "category_name", "") if card else "",
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
            logger.error("Error viewing public basket %s: %s", uuid_str, exc)
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
            logger.error("Error cloning public basket %s: %s", uuid_str, exc)
            flash(_("Error al guardar una copia de la canasta."), "error")
            return redirect(url_for("baskets"))

    @app.route("/optimize")
    def optimize():
        list_id = request.args.get("list_id")
        public_uuid = request.args.get("public_uuid")
        eans_str = request.args.get("eans", "").strip()

        with Session(public_engine) as pub_session:
            cat_repo = SqlAlchemyCatalogRepository(pub_session)
            price_repo = SqlAlchemyPriceRepository(pub_session)

            region = config.get_region()
            cities = cat_repo.get_cities_for_region(region)

            # Latest price date from DB
            latest_date = price_repo.get_latest_price_date()
            default_date_str = (
                latest_date.strftime("%Y-%m-%d")
                if latest_date
                else date.today().strftime("%Y-%m-%d")
            )
            selected_date_str = request.args.get("date", default_date_str)

            # Resolve selected city: default to first city in database region
            req_city = request.args.get("city")
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
        requested_items: List[BasketItem] = []
        try:
            with Session(user_engine) as u_session:
                user_repo = SqlAlchemyUserRepository(u_session)
                demo_user = _get_or_create_demo_user(user_repo)
                user_baskets = user_repo.get_user_baskets(user_id=demo_user.id)

                if public_uuid:
                    target_list = user_repo.get_basket_by_uuid(public_uuid)
                    if target_list and target_list.is_public:
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
                ean_list = [
                    e.strip() for e in re.split(r"[\s,]+", eans_str) if e.strip()
                ]

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

                with Session(public_engine) as pub_session:
                    cat_repo = SqlAlchemyCatalogRepository(pub_session)
                    price_repo = SqlAlchemyPriceRepository(pub_session)
                    use_case = OptimizeBasketUseCase(cat_repo, price_repo)
                    result = use_case.execute(
                        selected_city, target_date, requested_items
                    )

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
                flash(
                    _("Error al calcular los precios óptimos para la canasta."), "error"
                )

        return render_template_string(
            OPTIMIZE_TEMPLATE,
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

    return app


if __name__ == "__main__":
    import sys

    try:
        config = read_config()
        public_app = create_public_app()
        public_app.run(port=5000, debug=config.settings.app.debug)
    except Exception as exc:
        logger.error("Public server error: %s", exc)
        sys.exit(1)
