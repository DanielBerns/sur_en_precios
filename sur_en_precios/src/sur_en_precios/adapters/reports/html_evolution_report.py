"""Standalone interactive HTML report renderer for basket price evolution.

Compiles a zero-dependency, self-contained single-file HTML dashboard with embedded
SVG/Canvas visualizations, interactive client-side filtering, and Spanish UI localization.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from sur_en_precios.domain.ports_evolution import (
    EvolutionReportData,
    EvolutionReportRendererPort,
)

logger = logging.getLogger(__name__)

__all__ = ["HtmlBasketEvolutionReportRenderer"]


class HtmlBasketEvolutionReportRenderer(EvolutionReportRendererPort):
    """Generates an air-gapped, zero-CDN interactive HTML report."""

    def render(self, data: EvolutionReportData, output_path: Path) -> Path:
        """Serializes evolution data and writes a standalone interactive HTML dashboard."""
        serialized_payload = self._serialize_report_data(data)
        json_data_str = json.dumps(serialized_payload, ensure_ascii=False)

        html_content = self._generate_html(json_data_str, data)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html_content, encoding="utf-8")
        logger.info("Rendered evolution HTML report to %s", output_path)
        return output_path

    def _serialize_report_data(self, data: EvolutionReportData) -> Dict[str, Any]:
        """Converts domain objects into JSON-serializable dictionaries."""
        baskets_json = [
            {
                "key": b.basket_key,
                "name": b.name,
                "items_count": b.items_count,
                "composition_hash": b.composition_hash,
                "first_date": b.first_date.isoformat() if b.first_date else None,
                "last_date": b.last_date.isoformat() if b.last_date else None,
                "evaluations_count": b.evaluations_count,
            }
            for b in data.baskets
        ]

        summaries_json = [
            {
                "price_date": s.price_date.isoformat(),
                "basket_key": s.basket_key,
                "basket_name": s.basket_name,
                "region": s.region,
                "city": s.city,
                "composition_hash": s.composition_hash,
                "requested_items": s.requested_items_count,
                "matched_items": s.matched_items_count,
                "active_stores": s.active_stores_count,
                "complete_stores": s.complete_stores_count,
                "total_min_price": s.total_min_price,
                "total_reference_price": s.total_reference_price,
                "total_max_price": s.total_max_price,
                "best_store_code": s.best_store_code,
                "best_store_label": s.best_store_label,
                "best_store_total": s.best_store_total,
                "worst_store_label": s.worst_store_label,
                "worst_store_total": s.worst_store_total,
                "dispersion_pct": s.dispersion_pct,
                "store_dispersion_pct": s.store_dispersion_pct,
                "is_complete": s.is_complete,
            }
            for s in data.summaries
        ]

        trends_json: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        for b_key, city_dict in data.trends.items():
            trends_json[b_key] = {}
            for city_name, rows in city_dict.items():
                trends_json[b_key][city_name] = [
                    {
                        "date": r.price_date.isoformat(),
                        "min": r.record.total_min_price,
                        "ref": r.record.total_reference_price,
                        "max": r.record.total_max_price,
                        "best_store_label": r.record.best_store_label,
                        "best_store_total": r.record.best_store_total,
                        "dispersion_pct": r.record.dispersion_pct,
                        "change_prev_pct": r.change_prev_pct,
                        "change_base_pct": r.change_base_pct,
                        "comparable": r.comparable_with_prev,
                        "matched_items": r.record.matched_items_count,
                        "requested_items": r.record.requested_items_count,
                    }
                    for r in rows
                ]

        comparisons_json: Dict[str, Dict[str, Any]] = {}
        for b_key, (reg_ref, comp_rows) in data.city_comparisons.items():
            comparisons_json[b_key] = {
                "regional_reference": reg_ref,
                "rows": [
                    {
                        "city": c.record.city,
                        "ref": c.record.total_reference_price,
                        "min": c.record.total_min_price,
                        "max": c.record.total_max_price,
                        "best_store_label": c.record.best_store_label,
                        "best_store_total": c.record.best_store_total,
                        "dispersion_pct": c.record.dispersion_pct,
                        "gap_vs_regional_pct": c.gap_vs_regional_pct,
                        "rank": c.rank,
                        "is_complete": c.record.is_complete,
                        "matched_items": c.record.matched_items_count,
                        "requested_items": c.record.requested_items_count,
                    }
                    for c in comp_rows
                ],
            }

        rankings_json: Dict[str, List[Dict[str, Any]]] = {}
        for b_key, r_rows in data.store_rankings.items():
            rankings_json[b_key] = [
                {
                    "city": r.city,
                    "store_label": r.store_label,
                    "days_best": r.days_best,
                    "days_evaluated": r.days_evaluated,
                    "share_pct": r.share_pct,
                }
                for r in r_rows
            ]

        drivers_json: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        for b_key, city_drivers in data.inflation_drivers.items():
            drivers_json[b_key] = {}
            for city_name, d_list in city_drivers.items():
                drivers_json[b_key][city_name] = [
                    {
                        "ean": d.ean,
                        "product_name": d.product_name,
                        "quantity": d.quantity,
                        "numerator": d.numerator,
                        "denominator": d.denominator,
                        "initial_price": d.initial_price,
                        "latest_price": d.latest_price,
                        "initial_line_cost": d.initial_line_cost,
                        "latest_line_cost": d.latest_line_cost,
                        "cost_change": d.cost_change,
                        "change_pct": d.change_pct,
                        "weight_pct": d.weight_pct,
                        "contribution_pct": d.contribution_pct,
                        "latest_dispersion_pct": d.latest_dispersion_pct,
                        "cheapest_store_code": d.cheapest_store_code,
                    }
                    for d in d_list
                ]

        return {
            "generated_at": data.generated_at.isoformat(),
            "baskets": baskets_json,
            "cities": data.cities,
            "date_range": [
                data.date_range[0].isoformat() if data.date_range[0] else None,
                data.date_range[1].isoformat() if data.date_range[1] else None,
            ],
            "summaries": summaries_json,
            "trends": trends_json,
            "city_comparisons": comparisons_json,
            "store_rankings": rankings_json,
            "inflation_drivers": drivers_json,
        }

    def _generate_html(self, json_payload: str, data: EvolutionReportData) -> str:
        """Constructs the full HTML document string with inlined styles and scripts."""
        return f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sur en Precios — Evolución de Canastas Testigo (UNPSJB)</title>
    <style>
        :root {{
            --bg-main: #0b1120;
            --bg-card: #1e293b;
            --bg-card-hover: #24344d;
            --border: #334155;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --accent: #38bdf8;
            --accent-subtle: rgba(56, 189, 248, 0.15);
            --success: #22c55e;
            --success-subtle: rgba(34, 197, 94, 0.15);
            --danger: #ef4444;
            --danger-subtle: rgba(239, 68, 68, 0.15);
            --warning: #f59e0b;
            --warning-subtle: rgba(245, 158, 11, 0.15);
            --font: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }}

        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: var(--font);
            background-color: var(--bg-main);
            color: var(--text-main);
            line-height: 1.5;
            padding: 1.5rem;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}

        /* Header */
        header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            flex-wrap: wrap;
            gap: 1rem;
            padding-bottom: 1.5rem;
            border-bottom: 1px solid var(--border);
            margin-bottom: 1.5rem;
        }}

        .header-title h1 {{
            font-size: 1.75rem;
            color: var(--accent);
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}

        .header-title p {{
            color: var(--text-muted);
            font-size: 0.9rem;
            margin-top: 0.25rem;
        }}

        .header-badges {{
            display: flex;
            gap: 0.5rem;
            margin-top: 0.5rem;
            flex-wrap: wrap;
        }}

        .badge {{
            display: inline-flex;
            align-items: center;
            padding: 0.25rem 0.6rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
            background: var(--bg-card);
            border: 1px solid var(--border);
            color: var(--text-muted);
        }}
        .badge.accent {{ background: var(--accent-subtle); color: var(--accent); border-color: rgba(56, 189, 248, 0.3); }}
        .badge.success {{ background: var(--success-subtle); color: var(--success); border-color: rgba(34, 197, 94, 0.3); }}

        .header-actions {{
            display: flex;
            gap: 0.75rem;
        }}

        .btn {{
            background: var(--bg-card);
            color: var(--text-main);
            border: 1px solid var(--border);
            padding: 0.5rem 1rem;
            border-radius: 8px;
            font-size: 0.85rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s ease;
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
        }}
        .btn:hover {{ background: var(--bg-card-hover); border-color: var(--accent); color: var(--accent); }}
        .btn.primary {{ background: #0284c7; border-color: #0284c7; color: #fff; }}
        .btn.primary:hover {{ background: #0369a1; }}

        /* Filter Controls */
        .controls-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 1.25rem;
            margin-bottom: 1.5rem;
            display: flex;
            flex-wrap: wrap;
            gap: 1.25rem;
            align-items: flex-end;
        }}

        .form-group {{
            display: flex;
            flex-direction: column;
            gap: 0.4rem;
            flex: 1 1 200px;
        }}

        .form-group label {{
            font-size: 0.8rem;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}

        select, input[type="date"] {{
            background: #0f172a;
            border: 1px solid var(--border);
            color: var(--text-main);
            padding: 0.55rem 0.75rem;
            border-radius: 6px;
            font-size: 0.9rem;
            outline: none;
            width: 100%;
        }}
        select:focus, input[type="date"]:focus {{ border-color: var(--accent); }}

        /* KPI Cards Grid */
        .kpi-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 1rem;
            margin-bottom: 1.5rem;
        }}

        .kpi-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 1.25rem;
            position: relative;
            overflow: hidden;
        }}
        .kpi-card::before {{
            content: "";
            position: absolute;
            top: 0; left: 0; right: 0; height: 3px;
            background: var(--border);
        }}
        .kpi-card.accent::before {{ background: var(--accent); }}
        .kpi-card.success::before {{ background: var(--success); }}
        .kpi-card.warning::before {{ background: var(--warning); }}
        .kpi-card.danger::before {{ background: var(--danger); }}

        .kpi-label {{
            font-size: 0.75rem;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.25rem;
        }}

        .kpi-value {{
            font-size: 1.6rem;
            font-weight: 700;
            color: var(--text-main);
            letter-spacing: -0.02em;
        }}

        .kpi-subtext {{
            font-size: 0.8rem;
            color: var(--text-muted);
            margin-top: 0.25rem;
            display: flex;
            align-items: center;
            gap: 0.3rem;
        }}
        .trend-up {{ color: var(--danger); }}
        .trend-down {{ color: var(--success); }}
        .trend-neutral {{ color: var(--text-muted); }}

        /* Section Cards */
        .section-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
        }}

        .section-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.25rem;
            flex-wrap: wrap;
            gap: 0.5rem;
        }}

        .section-title {{
            font-size: 1.15rem;
            font-weight: 700;
            color: var(--text-main);
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}

        .series-toggles {{
            display: flex;
            gap: 1rem;
            flex-wrap: wrap;
        }}

        .toggle-item {{
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            font-size: 0.8rem;
            cursor: pointer;
            user-select: none;
        }}

        .toggle-color {{
            width: 10px;
            height: 10px;
            border-radius: 50%;
            display: inline-block;
        }}

        /* SVG Chart Styles */
        .chart-container {{
            width: 100%;
            height: 380px;
            position: relative;
        }}

        svg.evolution-chart {{
            width: 100%;
            height: 100%;
            overflow: visible;
        }}

        .chart-grid line {{ stroke: #334155; stroke-dasharray: 3 3; stroke-width: 0.75; }}
        .chart-axis text {{ fill: #94a3b8; font-size: 11px; }}
        .chart-axis line {{ stroke: #475569; stroke-width: 1; }}

        .line-ref {{ fill: none; stroke: #38bdf8; stroke-width: 2.5; stroke-linecap: round; stroke-linejoin: round; }}
        .line-min {{ fill: none; stroke: #22c55e; stroke-width: 1.8; stroke-dasharray: 4 2; stroke-linecap: round; }}
        .line-max {{ fill: none; stroke: #ef4444; stroke-width: 1.8; stroke-dasharray: 4 2; stroke-linecap: round; }}
        .line-best-store {{ fill: none; stroke: #f59e0b; stroke-width: 2; stroke-linecap: round; }}
        .area-spread {{ fill: rgba(56, 189, 248, 0.08); }}

        .chart-point {{
            cursor: pointer;
            transition: r 0.15s ease;
        }}
        .chart-point:hover {{ r: 6 !important; }}

        /* Tooltip */
        #chart-tooltip {{
            position: absolute;
            display: none;
            background: #0f172a;
            border: 1px solid var(--accent);
            border-radius: 8px;
            padding: 0.75rem;
            font-size: 0.8rem;
            color: #fff;
            pointer-events: none;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
            z-index: 50;
            min-width: 160px;
        }}

        /* Tabs */
        .tabs-nav {{
            display: flex;
            gap: 0.5rem;
            border-bottom: 1px solid var(--border);
            margin-bottom: 1.25rem;
            flex-wrap: wrap;
        }}

        .tab-btn {{
            background: transparent;
            border: none;
            border-bottom: 2px solid transparent;
            color: var(--text-muted);
            padding: 0.6rem 1rem;
            font-size: 0.9rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s ease;
        }}
        .tab-btn:hover {{ color: var(--text-main); }}
        .tab-btn.active {{ color: var(--accent); border-bottom-color: var(--accent); }}

        .tab-content {{ display: none; }}
        .tab-content.active {{ display: block; }}

        /* Data Tables */
        .table-responsive {{
            width: 100%;
            overflow-x: auto;
        }}

        table.data-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.85rem;
            text-align: left;
        }}

        table.data-table th {{
            background: #0f172a;
            color: var(--text-muted);
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.72rem;
            letter-spacing: 0.05em;
            padding: 0.75rem 1rem;
            border-bottom: 1px solid var(--border);
        }}

        table.data-table td {{
            padding: 0.75rem 1rem;
            border-bottom: 1px solid #1e293b;
            color: var(--text-main);
        }}

        table.data-table tr:hover td {{ background: var(--bg-card-hover); }}

        .text-right {{ text-align: right; }}
        .text-center {{ text-align: center; }}
        .font-mono {{ font-family: monospace; font-size: 0.9em; }}

        /* Bar Chart Rows */
        .bar-container {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
            margin-bottom: 0.75rem;
        }}
        .bar-label {{ width: 180px; font-size: 0.85rem; font-weight: 600; }}
        .bar-track {{ flex: 1; height: 24px; background: #0f172a; border-radius: 4px; overflow: hidden; position: relative; display: flex; align-items: center; }}
        .bar-fill {{ height: 100%; background: #0284c7; border-radius: 4px; transition: width 0.4s ease; }}
        .bar-val {{ width: 120px; font-size: 0.85rem; font-weight: 700; text-align: right; }}

        /* Empty state */
        .empty-state {{
            padding: 3rem;
            text-align: center;
            color: var(--text-muted);
        }}

        /* Print Media */
        @media print {{
            body {{ background: #fff; color: #000; padding: 0; }}
            .controls-card, .header-actions, .tabs-nav {{ display: none !important; }}
            .kpi-card, .section-card {{ border: 1px solid #ccc; background: #fff; color: #000; }}
            .kpi-value, .section-title {{ color: #000; }}
            svg.evolution-chart {{ background: #fff; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <header>
            <div class="header-title">
                <h1>🛒 Sur en Precios — Evolución de Canastas Testigo</h1>
                <p>Análisis histórico de precios, disparidad interurbana y motores de inflación en la Patagonia.</p>
                <div class="header-badges">
                    <span class="badge accent">UNPSJB Ingestion Server</span>
                    <span class="badge success">Modo 100% Offline</span>
                    <span class="badge">Generado: <span id="lbl-generated-at"></span></span>
                </div>
            </div>
            <div class="header-actions">
                <button class="btn primary" onclick="exportFilteredCSV()">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                    Exportar CSV
                </button>
                <button class="btn" onclick="window.print()">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 6 2 18 2 18 9"></polyline><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"></path><rect x="6" y="14" width="12" height="8"></rect></svg>
                    Imprimir / PDF
                </button>
            </div>
        </header>

        <!-- Control Bar -->
        <div class="controls-card">
            <div class="form-group" style="flex: 2 1 280px;">
                <label for="sel-basket">Canasta Testigo</label>
                <select id="sel-basket" onchange="onBasketChanged()"></select>
            </div>
            <div class="form-group" style="flex: 1.5 1 220px;">
                <label for="sel-city">Ciudad Principal</label>
                <select id="sel-city" onchange="onCityChanged()"></select>
            </div>
            <div class="form-group">
                <label for="dt-since">Desde</label>
                <input type="date" id="dt-since" onchange="onDateFilterChanged()">
            </div>
            <div class="form-group">
                <label for="dt-until">Hasta</label>
                <input type="date" id="dt-until" onchange="onDateFilterChanged()">
            </div>
            <div style="display: flex; align-items: flex-end;">
                <button class="btn" onclick="resetDateFilter()">Restablecer Fechas</button>
            </div>
        </div>

        <!-- KPI Grid -->
        <div class="kpi-grid">
            <div class="kpi-card accent">
                <div class="kpi-label">Precio Canasta de Referencia</div>
                <div class="kpi-value" id="kpi-ref-price">$ 0</div>
                <div class="kpi-subtext" id="kpi-ref-subtext">Media geométrica robusta</div>
            </div>
            <div class="kpi-card" id="kpi-card-variation">
                <div class="kpi-label">Variación en el Período</div>
                <div class="kpi-value" id="kpi-variation">0.0%</div>
                <div class="kpi-subtext" id="kpi-var-subtext">Inflación acumulada en ventana</div>
            </div>
            <div class="kpi-card warning">
                <div class="kpi-label">Mejor Comercio Único (100% Canasta)</div>
                <div class="kpi-value" id="kpi-best-store-price" style="font-size: 1.4rem;">$ 0</div>
                <div class="kpi-subtext" id="kpi-best-store-label">N/D</div>
            </div>
            <div class="kpi-card success">
                <div class="kpi-label">Brecha vs. Promedio Provincial</div>
                <div class="kpi-value" id="kpi-regional-gap">0.0%</div>
                <div class="kpi-subtext" id="kpi-regional-subtext">Comparativa interurbana</div>
            </div>
        </div>

        <!-- Section 1: Time Series Chart -->
        <div class="section-card">
            <div class="section-header">
                <div class="section-title">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>
                    Evolución Temporal del Costo de Canasta
                </div>
                <div class="series-toggles">
                    <label class="toggle-item">
                        <input type="checkbox" id="chk-show-ref" checked onchange="renderTimeSeriesChart()">
                        <span class="toggle-color" style="background: #38bdf8;"></span>
                        Referencia
                    </label>
                    <label class="toggle-item">
                        <input type="checkbox" id="chk-show-min" checked onchange="renderTimeSeriesChart()">
                        <span class="toggle-color" style="background: #22c55e;"></span>
                        Mínimo Óptimo
                    </label>
                    <label class="toggle-item">
                        <input type="checkbox" id="chk-show-max" checked onchange="renderTimeSeriesChart()">
                        <span class="toggle-color" style="background: #ef4444;"></span>
                        Máximo
                    </label>
                    <label class="toggle-item">
                        <input type="checkbox" id="chk-show-best-store" checked onchange="renderTimeSeriesChart()">
                        <span class="toggle-color" style="background: #f59e0b;"></span>
                        Mejor Comercio
                    </label>
                </div>
            </div>
            <div class="chart-container" id="time-series-container">
                <svg id="svg-time-series" class="evolution-chart"></svg>
                <div id="chart-tooltip"></div>
            </div>
        </div>

        <!-- Section 2: Detailed Tabs -->
        <div class="section-card">
            <div class="tabs-nav">
                <button class="tab-btn active" onclick="switchTab('tab-cities', this)">🏙️ Disparidad Interurbana</button>
                <button class="tab-btn" onclick="switchTab('tab-drivers', this)">📦 Motores de Inflación (Artículos)</button>
                <button class="tab-btn" onclick="switchTab('tab-stores', this)">🛒 Competitividad de Comercios</button>
                <button class="tab-btn" onclick="switchTab('tab-history', this)">📅 Historial Completo</button>
            </div>

            <!-- Tab: Inter-city Comparison -->
            <div id="tab-cities" class="tab-content active">
                <div style="margin-bottom: 1.5rem;" id="city-bars-container"></div>
                <div class="table-responsive">
                    <table class="data-table" id="tbl-city-comparison">
                        <thead>
                            <tr>
                                <th>Posición</th>
                                <th>Ciudad</th>
                                <th class="text-right">Canasta Referencia</th>
                                <th class="text-right">Mínimo Óptimo</th>
                                <th class="text-right">Máximo</th>
                                <th class="text-right">Brecha vs Región</th>
                                <th class="text-right">Dispersión Local</th>
                                <th>Mejor Comercio</th>
                                <th class="text-center">Completitud</th>
                            </tr>
                        </thead>
                        <tbody></tbody>
                    </table>
                </div>
            </div>

            <!-- Tab: Inflation Drivers -->
            <div id="tab-drivers" class="tab-content">
                <div class="table-responsive">
                    <table class="data-table" id="tbl-drivers">
                        <thead>
                            <tr>
                                <th>EAN</th>
                                <th>Descripción del Artículo</th>
                                <th class="text-center">Cant.</th>
                                <th class="text-right">Precio Inicial</th>
                                <th class="text-right">Precio Actual</th>
                                <th class="text-right">Variación Unit.</th>
                                <th class="text-right">Aporte a Canasta</th>
                                <th class="text-right">Peso en Canasta</th>
                                <th class="text-right">Dispersión Súpers</th>
                            </tr>
                        </thead>
                        <tbody></tbody>
                    </table>
                </div>
            </div>

            <!-- Tab: Store Rankings -->
            <div id="tab-stores" class="tab-content">
                <div style="margin-bottom: 1.5rem;" id="store-bars-container"></div>
                <div class="table-responsive">
                    <table class="data-table" id="tbl-stores">
                        <thead>
                            <tr>
                                <th>Ciudad</th>
                                <th>Comercio Supermercado</th>
                                <th class="text-right">Días Más Económico</th>
                                <th class="text-right">Días Evaluados</th>
                                <th class="text-right">% de Liderazgo en Precios</th>
                            </tr>
                        </thead>
                        <tbody></tbody>
                    </table>
                </div>
            </div>

            <!-- Tab: History Table -->
            <div id="tab-history" class="tab-content">
                <div class="table-responsive">
                    <table class="data-table" id="tbl-history">
                        <thead>
                            <tr>
                                <th>Fecha</th>
                                <th>Ciudad</th>
                                <th class="text-right">Referencia</th>
                                <th class="text-right">Mínimo</th>
                                <th class="text-right">Máximo</th>
                                <th>Mejor Súper</th>
                                <th class="text-right">Costo Mejor Súper</th>
                                <th class="text-right">Var. vs Ayer</th>
                                <th class="text-right">Dispersión</th>
                                <th class="text-center">Completitud</th>
                            </tr>
                        </thead>
                        <tbody></tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <!-- Data Injection -->
    <script id="evolution-data" type="application/json">
{json_payload}
    </script>

    <!-- Client-Side Vanilla Application Logic -->
    <script>
        const RAW_DATA = JSON.parse(document.getElementById('evolution-data').textContent);

        function formatARS(val) {{
            if (val === null || val === undefined) return 'N/D';
            return '$ ' + Math.round(val).toLocaleString('es-AR');
        }}

        function formatPct(val, showSign = true) {{
            if (val === null || val === undefined) return '-';
            const sign = (showSign && val > 0) ? '+' : '';
            return sign + val.toFixed(2) + '%';
        }}

        function initApp() {{
            document.getElementById('lbl-generated-at').textContent = 
                new Date(RAW_DATA.generated_at).toLocaleString('es-AR');

            // Populate Baskets
            const selBasket = document.getElementById('sel-basket');
            selBasket.innerHTML = '';
            RAW_DATA.baskets.forEach(b => {{
                const opt = document.createElement('option');
                opt.value = b.key;
                opt.textContent = `${{b.name}} (${{b.items_count}} ítems)`;
                selBasket.appendChild(opt);
            }});

            // Populate Cities
            const selCity = document.getElementById('sel-city');
            selCity.innerHTML = '';
            RAW_DATA.cities.forEach(c => {{
                const opt = document.createElement('option');
                opt.value = c;
                opt.textContent = c;
                selCity.appendChild(opt);
            }});

            // Init dates
            if (RAW_DATA.date_range && RAW_DATA.date_range[0]) {{
                document.getElementById('dt-since').value = RAW_DATA.date_range[0];
            }}
            if (RAW_DATA.date_range && RAW_DATA.date_range[1]) {{
                document.getElementById('dt-until').value = RAW_DATA.date_range[1];
            }}

            refreshDashboard();
        }}

        function getActiveBasketKey() {{
            return document.getElementById('sel-basket').value;
        }}

        function getActiveCity() {{
            return document.getElementById('sel-city').value;
        }}

        function onBasketChanged() {{ refreshDashboard(); }}
        function onCityChanged() {{ refreshDashboard(); }}
        function onDateFilterChanged() {{ refreshDashboard(); }}
        function resetDateFilter() {{
            if (RAW_DATA.date_range) {{
                document.getElementById('dt-since').value = RAW_DATA.date_range[0] || '';
                document.getElementById('dt-until').value = RAW_DATA.date_range[1] || '';
            }}
            refreshDashboard();
        }}

        function switchTab(tabId, btn) {{
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            btn.classList.add('active');
        }}

        function refreshDashboard() {{
            const basketKey = getActiveBasketKey();
            const city = getActiveCity();
            const since = document.getElementById('dt-since').value;
            const until = document.getElementById('dt-until').value;

            updateKPICards(basketKey, city, since, until);
            renderTimeSeriesChart();
            renderCityComparison(basketKey);
            renderInflationDrivers(basketKey, city);
            renderStoreRankings(basketKey);
            renderHistoryTable(basketKey, city, since, until);
        }}

        function getFilteredSeries(basketKey, city, since, until) {{
            const trends = (RAW_DATA.trends[basketKey] || {{}})[city] || [];
            return trends.filter(r => (!since || r.date >= since) && (!until || r.date <= until));
        }}

        function updateKPICards(basketKey, city, since, until) {{
            const series = getFilteredSeries(basketKey, city, since, until);
            if (!series.length) {{
                document.getElementById('kpi-ref-price').textContent = 'N/D';
                document.getElementById('kpi-variation').textContent = '-';
                document.getElementById('kpi-best-store-price').textContent = 'N/D';
                document.getElementById('kpi-best-store-label').textContent = 'Sin datos';
                document.getElementById('kpi-regional-gap').textContent = '-';
                return;
            }}

            const latest = series[series.length - 1];
            const first = series[0];

            document.getElementById('kpi-ref-price').textContent = formatARS(latest.ref);
            document.getElementById('kpi-ref-subtext').textContent = `Fecha: ${{latest.date}} (${{latest.matched_items}}/${{latest.requested_items}} ítems)`;

            // Variation
            let varPct = null;
            if (first.ref && latest.ref && first.ref > 0) {{
                varPct = ((latest.ref - first.ref) / first.ref) * 100;
            }}
            const kpiVarEl = document.getElementById('kpi-variation');
            kpiVarEl.textContent = formatPct(varPct);
            const kpiCardVar = document.getElementById('kpi-card-variation');
            kpiCardVar.className = 'kpi-card ' + (varPct > 0 ? 'danger' : (varPct < 0 ? 'success' : ''));

            // Best store
            document.getElementById('kpi-best-store-price').textContent = formatARS(latest.best_store_total);
            document.getElementById('kpi-best-store-label').textContent = latest.best_store_label || 'Sin súper con 100% de canasta';

            // Regional Gap
            const comparisons = RAW_DATA.city_comparisons[basketKey];
            if (comparisons && comparisons.rows) {{
                const cityRow = comparisons.rows.find(r => r.city.toLowerCase() === city.toLowerCase());
                if (cityRow && cityRow.gap_vs_regional_pct !== null && cityRow.gap_vs_regional_pct !== undefined) {{
                    document.getElementById('kpi-regional-gap').textContent = formatPct(cityRow.gap_vs_regional_pct);
                    document.getElementById('kpi-regional-subtext').textContent = `Ref Provincial: ${{formatARS(comparisons.regional_reference)}}`;
                }} else {{
                    document.getElementById('kpi-regional-gap').textContent = 'N/D';
                    document.getElementById('kpi-regional-subtext').textContent = 'Canasta incompleta en ciudad';
                }}
            }}
        }}

        function renderTimeSeriesChart() {{
            const svg = document.getElementById('svg-time-series');
            svg.innerHTML = '';
            const basketKey = getActiveBasketKey();
            const city = getActiveCity();
            const since = document.getElementById('dt-since').value;
            const until = document.getElementById('dt-until').value;

            const series = getFilteredSeries(basketKey, city, since, until);
            const container = document.getElementById('time-series-container');
            const width = container.clientWidth || 900;
            const height = 360;
            svg.setAttribute('viewBox', `0 0 ${{width}} ${{height}}`);

            if (series.length < 1) {{
                const txt = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                txt.setAttribute('x', width / 2);
                txt.setAttribute('y', height / 2);
                txt.setAttribute('text-anchor', 'middle');
                txt.setAttribute('fill', '#94a3b8');
                txt.textContent = 'No hay datos de evolución para el período y ciudad seleccionados.';
                svg.appendChild(txt);
                return;
            }}

            const padLeft = 80;
            const padRight = 30;
            const padTop = 20;
            const padBottom = 40;
            const plotW = width - padLeft - padRight;
            const plotH = height - padTop - padBottom;

            // Find min/max values
            const allVals = [];
            series.forEach(r => {{
                if (r.ref) allVals.push(r.ref);
                if (r.min) allVals.push(r.min);
                if (r.max) allVals.push(r.max);
                if (r.best_store_total) allVals.push(r.best_store_total);
            }});

            const minVal = allVals.length ? Math.min(...allVals) * 0.96 : 0;
            const maxVal = allVals.length ? Math.max(...allVals) * 1.04 : 1000;

            const getX = idx => padLeft + (series.length === 1 ? plotW / 2 : (idx / (series.length - 1)) * plotW);
            const getY = val => padTop + plotH - ((val - minVal) / (maxVal - minVal)) * plotH;

            // Grid lines
            const gridG = document.createElementNS('http://www.w3.org/2000/svg', 'g');
            gridG.setAttribute('class', 'chart-grid');
            const yTicks = 5;
            for (let i = 0; i <= yTicks; i++) {{
                const tickVal = minVal + (i / yTicks) * (maxVal - minVal);
                const yPos = getY(tickVal);
                const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
                line.setAttribute('x1', padLeft);
                line.setAttribute('x2', width - padRight);
                line.setAttribute('y1', yPos);
                line.setAttribute('y2', yPos);
                gridG.appendChild(line);

                const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                label.setAttribute('x', padLeft - 10);
                label.setAttribute('y', yPos + 4);
                label.setAttribute('text-anchor', 'end');
                label.setAttribute('fill', '#94a3b8');
                label.setAttribute('font-size', '10');
                label.textContent = formatARS(tickVal);
                gridG.appendChild(label);
            }}
            svg.appendChild(gridG);

            // Shaded spread area between Min and Max
            const showMin = document.getElementById('chk-show-min').checked;
            const showMax = document.getElementById('chk-show-max').checked;
            if (showMin && showMax && series.length > 1) {{
                let areaPath = `M ${{getX(0)}} ${{getY(series[0].max || series[0].ref)}}`;
                for (let i = 1; i < series.length; i++) {{
                    areaPath += ` L ${{getX(i)}} ${{getY(series[i].max || series[i].ref)}}`;
                }}
                for (let i = series.length - 1; i >= 0; i--) {{
                    areaPath += ` L ${{getX(i)}} ${{getY(series[i].min || series[i].ref)}}`;
                }}
                areaPath += ' Z';
                const areaEl = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                areaEl.setAttribute('d', areaPath);
                areaEl.setAttribute('class', 'area-spread');
                svg.appendChild(areaEl);
            }}

            // Draw series curves
            function drawPath(prop, cssClass, color) {{
                let d = '';
                series.forEach((pt, idx) => {{
                    const val = pt[prop];
                    if (val !== null && val !== undefined) {{
                        const cmd = d === '' ? 'M' : 'L';
                        d += ` ${{cmd}} ${{getX(idx)}} ${{getY(val)}}`;
                    }}
                }});
                if (d) {{
                    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                    path.setAttribute('d', d);
                    path.setAttribute('class', cssClass);
                    svg.appendChild(path);
                }}
            }}

            if (showMax) drawPath('max', 'line-max', '#ef4444');
            if (showMin) drawPath('min', 'line-min', '#22c55e');
            if (document.getElementById('chk-show-best-store').checked) drawPath('best_store_total', 'line-best-store', '#f59e0b');
            if (document.getElementById('chk-show-ref').checked) drawPath('ref', 'line-ref', '#38bdf8');

            // Interactive Points & X-Axis Labels
            const tooltip = document.getElementById('chart-tooltip');
            series.forEach((pt, idx) => {{
                const xPos = getX(idx);

                // Date label on X axis
                const dateLabel = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                dateLabel.setAttribute('x', xPos);
                dateLabel.setAttribute('y', height - 12);
                dateLabel.setAttribute('text-anchor', 'middle');
                dateLabel.setAttribute('fill', '#94a3b8');
                dateLabel.setAttribute('font-size', '10');
                const parts = pt.date.split('-');
                dateLabel.textContent = parts.length === 3 ? `${{parts[2]}}/${{parts[1]}}` : pt.date;
                svg.appendChild(dateLabel);

                // Point for reference line
                if (pt.ref !== null && pt.ref !== undefined) {{
                    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
                    circle.setAttribute('cx', xPos);
                    circle.setAttribute('cy', getY(pt.ref));
                    circle.setAttribute('r', '4');
                    circle.setAttribute('fill', '#38bdf8');
                    circle.setAttribute('class', 'chart-point');

                    circle.addEventListener('mouseenter', e => {{
                        tooltip.style.display = 'block';
                        tooltip.innerHTML = `
                            <strong>📅 ${{pt.date}}</strong><br>
                            <span style="color:#38bdf8">Ref: ${{formatARS(pt.ref)}}</span><br>
                            <span style="color:#22c55e">Mín: ${{formatARS(pt.min)}}</span><br>
                            <span style="color:#ef4444">Máx: ${{formatARS(pt.max)}}</span><br>
                            <span style="color:#f59e0b">Mejor Súper: ${{formatARS(pt.best_store_total)}} (${{pt.best_store_label || 'N/D'}})</span><br>
                            Dispersión: ${{pt.dispersion_pct ? pt.dispersion_pct.toFixed(1) + '%' : '-'}}
                        `;
                    }});
                    circle.addEventListener('mousemove', e => {{
                        const rect = container.getBoundingClientRect();
                        tooltip.style.left = (e.clientX - rect.left + 15) + 'px';
                        tooltip.style.top = (e.clientY - rect.top - 15) + 'px';
                    }});
                    circle.addEventListener('mouseleave', () => {{
                        tooltip.style.display = 'none';
                    }});
                    svg.appendChild(circle);
                }}
            }});
        }}

        function renderCityComparison(basketKey) {{
            const comp = RAW_DATA.city_comparisons[basketKey];
            const tbody = document.querySelector('#tbl-city-comparison tbody');
            tbody.innerHTML = '';
            const barsContainer = document.getElementById('city-bars-container');
            barsContainer.innerHTML = '';

            if (!comp || !comp.rows || !comp.rows.length) {{
                tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No hay evaluaciones comparativas.</td></tr>';
                return;
            }}

            const maxPrice = Math.max(...comp.rows.map(r => r.ref || 0), 1);

            comp.rows.forEach(r => {{
                // Table Row
                const tr = document.createElement('tr');
                const gapColor = r.gap_vs_regional_pct > 0 ? 'trend-up' : (r.gap_vs_regional_pct < 0 ? 'trend-down' : '');
                tr.innerHTML = `
                    <td class="text-center font-mono">#${{r.rank || '-'}}</td>
                    <td><strong>${{r.city}}</strong></td>
                    <td class="text-right"><strong>${{formatARS(r.ref)}}</strong></td>
                    <td class="text-right" style="color:var(--success);">${{formatARS(r.min)}}</td>
                    <td class="text-right" style="color:var(--danger);">${{formatARS(r.max)}}</td>
                    <td class="text-right ${{gapColor}}">${{formatPct(r.gap_vs_regional_pct)}}</td>
                    <td class="text-right">${{formatPct(r.dispersion_pct, false)}}</td>
                    <td>${{r.best_store_label || '<span style="color:var(--text-muted)">N/D</span>'}}</td>
                    <td class="text-center font-mono">${{r.matched_items}}/${{r.requested_items}}</td>
                `;
                tbody.appendChild(tr);

                // Horizontal Bar
                if (r.ref) {{
                    const barRow = document.createElement('div');
                    barRow.className = 'bar-container';
                    const pctWidth = ((r.ref / maxPrice) * 100).toFixed(1);
                    barRow.innerHTML = `
                        <div class="bar-label">${{r.city}}</div>
                        <div class="bar-track">
                            <div class="bar-fill" style="width: ${{pctWidth}}%;"></div>
                        </div>
                        <div class="bar-val">${{formatARS(r.ref)}}</div>
                    `;
                    barsContainer.appendChild(barRow);
                }}
            }});
        }}

        function renderInflationDrivers(basketKey, city) {{
            const tbody = document.querySelector('#tbl-drivers tbody');
            tbody.innerHTML = '';

            const cityDrivers = (RAW_DATA.inflation_drivers[basketKey] || {{}})[city] || [];
            if (!cityDrivers.length) {{
                tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No hay datos de desglose para esta ciudad.</td></tr>';
                return;
            }}

            cityDrivers.forEach(d => {{
                const tr = document.createElement('tr');
                const changeColor = d.cost_change > 0 ? 'trend-up' : (d.cost_change < 0 ? 'trend-down' : '');
                tr.innerHTML = `
                    <td class="font-mono">${{d.ean}}</td>
                    <td><strong>${{d.product_name}}</strong></td>
                    <td class="text-center font-mono">${{d.quantity}}</td>
                    <td class="text-right">${{formatARS(d.initial_price)}}</td>
                    <td class="text-right"><strong>${{formatARS(d.latest_price)}}</strong></td>
                    <td class="text-right ${{changeColor}}">${{formatPct(d.change_pct)}}</td>
                    <td class="text-right ${{changeColor}}">${{formatPct(d.contribution_pct)}}</td>
                    <td class="text-right">${{formatPct(d.weight_pct, false)}}</td>
                    <td class="text-right">${{formatPct(d.latest_dispersion_pct, false)}}</td>
                `;
                tbody.appendChild(tr);
            }});
        }}

        function renderStoreRankings(basketKey) {{
            const rankings = RAW_DATA.store_rankings[basketKey] || [];
            const tbody = document.querySelector('#tbl-stores tbody');
            tbody.innerHTML = '';
            const barsContainer = document.getElementById('store-bars-container');
            barsContainer.innerHTML = '';

            if (!rankings.length) {{
                tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No hay registros de supermercados para esta canasta.</td></tr>';
                return;
            }}

            rankings.forEach(r => {{
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td><strong>${{r.city}}</strong></td>
                    <td>${{r.store_label}}</td>
                    <td class="text-right font-mono">${{r.days_best}}</td>
                    <td class="text-right font-mono">${{r.days_evaluated}}</td>
                    <td class="text-right"><strong>${{r.share_pct.toFixed(1)}}%</strong></td>
                `;
                tbody.appendChild(tr);

                const barRow = document.createElement('div');
                barRow.className = 'bar-container';
                barRow.innerHTML = `
                    <div class="bar-label" style="width:240px;">${{r.city}} — ${{r.store_label.substring(0, 24)}}</div>
                    <div class="bar-track">
                        <div class="bar-fill" style="width: ${{r.share_pct}}%; background:#f59e0b;"></div>
                    </div>
                    <div class="bar-val">${{r.share_pct.toFixed(1)}}% (${{r.days_best}}d)</div>
                `;
                barsContainer.appendChild(barRow);
            }});
        }}

        function renderHistoryTable(basketKey, city, since, until) {{
            const tbody = document.querySelector('#tbl-history tbody');
            tbody.innerHTML = '';
            const series = getFilteredSeries(basketKey, city, since, until);

            if (!series.length) {{
                tbody.innerHTML = '<tr><td colspan="10" class="empty-state">No hay registros históricos.</td></tr>';
                return;
            }}

            // Reverse order to show newest first
            [...series].reverse().forEach(r => {{
                const tr = document.createElement('tr');
                const chgColor = r.change_prev_pct > 0 ? 'trend-up' : (r.change_prev_pct < 0 ? 'trend-down' : '');
                tr.innerHTML = `
                    <td class="font-mono"><strong>${{r.date}}</strong></td>
                    <td>${{city}}</td>
                    <td class="text-right"><strong>${{formatARS(r.ref)}}</strong></td>
                    <td class="text-right" style="color:var(--success);">${{formatARS(r.min)}}</td>
                    <td class="text-right" style="color:var(--danger);">${{formatARS(r.max)}}</td>
                    <td>${{r.best_store_label || '<span style="color:var(--text-muted)">N/D</span>'}}</td>
                    <td class="text-right">${{formatARS(r.best_store_total)}}</td>
                    <td class="text-right ${{chgColor}}">${{formatPct(r.change_prev_pct)}}</td>
                    <td class="text-right">${{formatPct(r.dispersion_pct, false)}}</td>
                    <td class="text-center font-mono">${{r.matched_items}}/${{r.requested_items}}</td>
                `;
                tbody.appendChild(tr);
            }});
        }}

        function exportFilteredCSV() {{
            const basketKey = getActiveBasketKey();
            const city = getActiveCity();
            const since = document.getElementById('dt-since').value;
            const until = document.getElementById('dt-until').value;
            const series = getFilteredSeries(basketKey, city, since, until);

            let csv = 'fecha,canasta,ciudad,precio_referencia,precio_minimo,precio_maximo,mejor_comercio,precio_mejor_comercio,dispersion_pct,articulos_cubiertos,articulos_solicitados\\n';
            series.forEach(r => {{
                csv += `${{r.date}},"${{basketKey}}","${{city}}",${{r.ref || ''}},${{r.min || ''}},${{r.max || ''}},"${{r.best_store_label || ''}}",${{r.best_store_total || ''}},${{r.dispersion_pct || ''}},${{r.matched_items}},${{r.requested_items}}\\n`;
            }});

            const blob = new Blob([csv], {{ type: 'text/csv;charset=utf-8;' }});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `evolucion_${{basketKey}}_${{city}}_${{new Date().toISOString().slice(0,10)}}.csv`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }}

        window.addEventListener('resize', renderTimeSeriesChart);
        window.addEventListener('DOMContentLoaded', initApp);
    </script>
</body>
</html>"""
