"""CLI tool to evaluate and analyze basket price evolution across regional cities.

Executed on the UNPSJB ingestion server after the daily update of public.sqlite
to record time-series basket metrics into evolution.sqlite.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import List, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sur_en_precios.adapters.database.evolution_db import (
    create_evolution_engine,
    upgrade_evolution_schema,
)
from sur_en_precios.adapters.database.repositories import (
    SqlAlchemyCatalogRepository,
    SqlAlchemyPriceRepository,
)
from sur_en_precios.adapters.database.repositories_evolution import (
    SqlAlchemyEvolutionRepository,
)
from sur_en_precios.adapters.logging import setup_application_logging
from sur_en_precios.adapters.reports.html_evolution_report import (
    HtmlBasketEvolutionReportRenderer,
)
from sur_en_precios.config import Config, read_config
from sur_en_precios.use_cases.analyze_basket_evolution import (
    AnalyzeBasketEvolutionUseCase,
)
from sur_en_precios.use_cases.evaluate_basket_evolution import (
    EvaluateBasketEvolutionUseCase,
    EvolutionExecutionResult,
)
from sur_en_precios.use_cases.generate_basket_evolution_report import (
    GenerateBasketEvolutionReportUseCase,
)

logger = logging.getLogger("sur_en_precios.evolution")

__all__ = ["generate_evolution_html_report", "main", "run_basket_evolution"]


def run_basket_evolution(
    config: Config,
    target_date: Optional[date] = None,
    region: Optional[str] = None,
    cities: Optional[List[str]] = None,
    baskets_dir_override: Optional[Path] = None,
) -> EvolutionExecutionResult:
    """Executes the daily evaluation of benchmark baskets against public.sqlite.

    Idempotently records min, reference, max, and store totals into evolution.sqlite.
    """
    public_db_path = config.get_public_db_path()
    if not public_db_path.exists() or public_db_path.stat().st_size == 0:
        raise FileNotFoundError(
            f"El catálogo de precios '{public_db_path}' no existe o está vacío. "
            "Ejecute 'run_etl' antes de evaluar la evolución."
        )

    evolution_db_path = config.get_evolution_db_path()
    # 1. Apply any pending Alembic migrations on evolution.sqlite
    upgrade_evolution_schema(evolution_db_path)

    # 2. Setup engines and sessions
    public_engine = create_engine(f"sqlite:///{public_db_path}")
    evolution_engine = create_evolution_engine(evolution_db_path)

    target_region = region or config.get_region()
    baskets_dir = baskets_dir_override or config.baskets_dir

    with (
        Session(public_engine) as pub_session,
        Session(evolution_engine) as evo_session,
    ):
        cat_repo = SqlAlchemyCatalogRepository(pub_session)
        price_repo = SqlAlchemyPriceRepository(pub_session)
        evo_repo = SqlAlchemyEvolutionRepository(evo_session)

        use_case = EvaluateBasketEvolutionUseCase(
            catalog_repo=cat_repo,
            price_repo=price_repo,
            evolution_repo=evo_repo,
        )

        return use_case.execute(
            region=target_region,
            target_date=target_date,
            cities=cities,
            baskets_dir=baskets_dir,
        )


def generate_evolution_html_report(
    config: Config,
    output_path: Optional[Path] = None,
    basket_key: Optional[str] = None,
    since: Optional[date] = None,
    until: Optional[date] = None,
    archive_path: Optional[Path] = None,
) -> Path:
    """Generates the standalone interactive HTML report for basket price evolution.

    Queries evolution.sqlite in read-only mode and writes the compiled self-contained
    HTML dashboard to the target location.
    """
    evolution_db_path = config.get_evolution_db_path()
    if not evolution_db_path.exists():
        raise FileNotFoundError(
            f"La base de datos de evolución '{evolution_db_path}' no existe. "
            "Ejecute primero con '--evaluate' para registrar datos."
        )

    target_path = output_path or (
        config.evolution_reports_dir / "evolution_latest.html"
    )
    evo_engine = create_evolution_engine(evolution_db_path)

    with Session(evo_engine) as session:
        evo_repo = SqlAlchemyEvolutionRepository(session)
        renderer = HtmlBasketEvolutionReportRenderer()
        use_case = GenerateBasketEvolutionReportUseCase(
            evolution_repo=evo_repo,
            report_renderer=renderer,
        )
        return use_case.execute(
            output_path=target_path,
            basket_key=basket_key,
            since=since,
            until=until,
            archive_path=archive_path,
        )


# ---------------------------------------------------------------------------
# Formatting and reporting helpers
# ---------------------------------------------------------------------------


def _format_ars(amount: Optional[int]) -> str:
    if amount is None:
        return "N/D"
    return f"${amount:,.0f}".replace(",", ".")


def _format_pct(val: Optional[float]) -> str:
    if val is None:
        return "-"
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.2f}%"


def print_evaluation_summary(result: EvolutionExecutionResult) -> None:
    """Prints a clean CLI summary of the evaluation execution."""
    print("=" * 70)
    print("🛒 Sur en Precios — Registro de Evolución de Canastas")
    print("=" * 70)
    date_str = result.price_date.isoformat() if result.price_date else "N/D"
    print(f"Fecha evaluada:      {date_str}")
    print(f"Región:              {result.region}")
    print(f"Canastas procesadas: {result.baskets_evaluated}/{result.baskets_loaded}")
    print(f"Ciudades evaluadas:  {result.cities_count}")
    print(f"Total evaluaciones:  {result.evaluations_count}")

    if result.load_errors:
        print("\n[!] Advertencias al cargar canastas:")
        for err in result.load_errors:
            print(f"  - {err}")

    if result.evaluation_errors:
        print("\n[!] Errores en la evaluación:")
        for err in result.evaluation_errors:
            print(f"  - {err}")

    for basket_key, evals in result.evaluations.items():
        print(f"\n--- Canasta: {basket_key} ---")
        header = f"{'Ciudad':<22} | {'Mínimo':>10} | {'Referencia':>12} | {'Máximo':>10} | {'Mejor Comercio':<24} | {'Completitud':>11}"
        print(header)
        print("-" * len(header))
        for ev in evals:
            complete_str = f"{ev.matched_items_count}/{ev.requested_items_count}"
            store_str = (ev.best_store_label or "N/D")[:24]
            print(
                f"{ev.city:<22} | "
                f"{_format_ars(ev.total_min_price):>10} | "
                f"{_format_ars(ev.total_reference_price):>12} | "
                f"{_format_ars(ev.total_max_price):>10} | "
                f"{store_str:<24} | "
                f"{complete_str:>11}"
            )
    print("=" * 70 + "\n")


def print_baskets_list(analyzer: AnalyzeBasketEvolutionUseCase) -> None:
    """Lists benchmark baskets tracked in evolution.sqlite."""
    baskets = analyzer.list_tracked_baskets()
    if not baskets:
        print("No hay canastas registradas en la base de datos de evolución.")
        return

    print("=" * 80)
    print("📋 Canastas Registradas en la Base de Evolución")
    print("=" * 80)
    header = (
        f"{'Clave (Key)':<32} | {'Nombre':<28} | {'Ítems':>5} | {'Rango Fechas':<23}"
    )
    print(header)
    print("-" * len(header))
    for b in baskets:
        dates = f"{b.first_date or 'N/D'} -> {b.last_date or 'N/D'}"
        print(
            f"{b.basket_key:<32} | {b.name[:28]:<28} | {b.items_count:>5} | {dates:<23}"
        )
    print("=" * 80)


def print_trend_report(
    analyzer: AnalyzeBasketEvolutionUseCase,
    basket_key: str,
    city: Optional[str] = None,
    since: Optional[date] = None,
    until: Optional[date] = None,
) -> None:
    """Prints time-series inflation trend for a basket in a city."""
    rows = analyzer.get_trend(
        basket_key=basket_key, city=city, since=since, until=until
    )
    if not rows:
        print(
            f"No se encontraron registros de evolución para la canasta '{basket_key}'."
        )
        return

    target_city = city or rows[0].record.city
    print("=" * 85)
    print(
        f"📈 Evolución de Precios: Canasta '{rows[0].record.basket_name}' en {target_city}"
    )
    print("=" * 85)
    header = f"{'Fecha':<10} | {'Mínimo':>10} | {'Referencia':>12} | {'Máximo':>10} | {'Var % Ant':>10} | {'Var % Base':>10} | {'Mejor Comercio':<18}"
    print(header)
    print("-" * len(header))
    for r in rows:
        rec = r.record
        store_label = (rec.best_store_label or "N/D")[:18]
        print(
            f"{r.price_date.isoformat():<10} | "
            f"{_format_ars(rec.total_min_price):>10} | "
            f"{_format_ars(rec.total_reference_price):>12} | "
            f"{_format_ars(rec.total_max_price):>10} | "
            f"{_format_pct(r.change_prev_pct):>10} | "
            f"{_format_pct(r.change_base_pct):>10} | "
            f"{store_label:<18}"
        )
    print("=" * 85)


def print_city_comparison_report(
    analyzer: AnalyzeBasketEvolutionUseCase,
    basket_key: str,
    target_date: Optional[date] = None,
) -> None:
    """Prints inter-city comparison for a basket on a given date."""
    reg_mean, rows = analyzer.compare_cities_on_date(
        basket_key=basket_key, target_date=target_date
    )
    if not rows:
        print(
            f"No hay evaluaciones para la canasta '{basket_key}' en la fecha solicitada."
        )
        return

    date_str = rows[0].record.price_date.isoformat()
    print("=" * 90)
    print(
        f"🏙️  Comparación Interurbana: Canasta '{rows[0].record.basket_name}' ({date_str})"
    )
    print(f"Referencia Regional (Media Geométrica): {_format_ars(reg_mean)}")
    print("=" * 90)
    header = f"{'Puesto':>6} | {'Ciudad':<22} | {'Referencia':>12} | {'Brecha Reg %':>12} | {'Mínimo':>10} | {'Dispersión %':>12} | {'Comercio Más Barato':<20}"
    print(header)
    print("-" * len(header))
    for r in rows:
        rec = r.record
        rank_str = str(r.rank) if r.rank > 0 else "-"
        store_str = (rec.best_store_label or "N/D")[:20]
        disp_str = (
            f"{rec.dispersion_pct:.1f}%" if rec.dispersion_pct is not None else "-"
        )
        print(
            f"{rank_str:>6} | "
            f"{rec.city:<22} | "
            f"{_format_ars(rec.total_reference_price):>12} | "
            f"{_format_pct(r.gap_vs_regional_pct):>12} | "
            f"{_format_ars(rec.total_min_price):>10} | "
            f"{disp_str:>12} | "
            f"{store_str:<20}"
        )
    print("=" * 90)


def print_store_rankings_report(
    analyzer: AnalyzeBasketEvolutionUseCase,
    basket_key: str,
    city: Optional[str] = None,
    since: Optional[date] = None,
    until: Optional[date] = None,
) -> None:
    """Prints store ranking report showing which stores are most frequently cheapest."""
    rankings = analyzer.rank_stores(
        basket_key=basket_key, city=city, since=since, until=until
    )
    if not rankings:
        print(f"No hay datos de comercios evaluados para la canasta '{basket_key}'.")
        return

    print("=" * 80)
    print(f"🏆 Ranking de Comercios Más Económicos — Canasta '{basket_key}'")
    print("=" * 80)
    header = f"{'Ciudad':<22} | {'Comercio':<32} | {'Días Barato':>11} | {'Total Eval':>10} | {'Frecuencia':>10}"
    print(header)
    print("-" * len(header))
    for r in rankings:
        print(
            f"{r.city:<22} | "
            f"{r.store_label[:32]:<32} | "
            f"{r.days_best:>11} | "
            f"{r.days_evaluated:>10} | "
            f"{r.share_pct:>9.1f}%"
        )
    print("=" * 80)


def export_data(
    analyzer: AnalyzeBasketEvolutionUseCase,
    format_type: str,
    level: str,
    basket_key: Optional[str] = None,
    city: Optional[str] = None,
    since: Optional[date] = None,
    until: Optional[date] = None,
    output_path: Optional[Path] = None,
) -> None:
    """Exports evolution data to CSV or JSON."""
    if level == "items":
        rows = analyzer.export_items(basket_key=basket_key, since=since, until=until)
    else:
        rows = analyzer.export_summaries(
            basket_key=basket_key, city=city, since=since, until=until
        )

    if not rows:
        print(
            "No se encontraron registros para exportar con los filtros indicados.",
            file=sys.stderr,
        )
        return

    if format_type == "json":
        output_str = json.dumps(rows, indent=2, ensure_ascii=False)
    else:
        buf = io.StringIO()
        fieldnames = list(rows[0].keys())
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        output_str = buf.getvalue()

    if output_path:
        out_file = Path(output_path).expanduser().resolve()
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(output_str, encoding="utf-8")
        print(f"Exportación exitosa ({len(rows)} filas) en: {out_file}")
    else:
        sys.stdout.write(output_str)


# ---------------------------------------------------------------------------
# CLI Argument Parser
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Herramienta de Registro y Análisis de Evolución de Precios de Canastas (UNPSJB)."
    )
    parser.add_argument(
        "--workdir", help="Directorio de trabajo (por defecto ~/Info/sur_en_precios)"
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--evaluate",
        action="store_true",
        help="Evalúa las canastas descargadas contra el catálogo más reciente de public.sqlite",
    )
    mode_group.add_argument(
        "--report",
        choices=["trend", "compare", "stores"],
        help="Genera un reporte analítico: 'trend' (serie temporal), 'compare' (interurbano), 'stores' (ranking comercios)",
    )
    mode_group.add_argument(
        "--list",
        action="store_true",
        help="Lista todas las canastas seguidas en la base de evolución",
    )
    mode_group.add_argument(
        "--export",
        choices=["csv", "json"],
        help="Exporta los datos de evolución a formato CSV o JSON",
    )
    mode_group.add_argument(
        "--html",
        nargs="?",
        const="",
        help="Genera un reporte interactivo HTML autónomo (opcionalmente especificar ruta destino)",
    )

    parser.add_argument(
        "--open",
        action="store_true",
        help="Abre automáticamente el reporte HTML generado en el navegador web local",
    )
    parser.add_argument(
        "--date", help="Fecha específica a evaluar o consultar (YYYY-MM-DD)"
    )
    parser.add_argument("--region", help="Código de región (ej. AR-U para Chubut)")
    parser.add_argument("--cities", help="Lista de ciudades separadas por coma")
    parser.add_argument(
        "--baskets-dir", help="Directorio con archivos YAML de canastas"
    )
    parser.add_argument("--basket", help="Clave (slug o uuid) de la canasta")
    parser.add_argument("--city", help="Nombre de ciudad para reportes específicos")
    parser.add_argument(
        "--since", help="Fecha inicial para series temporales (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--until", help="Fecha final para series temporales (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--level",
        choices=["summaries", "items"],
        default="summaries",
        help="Nivel de granularidad para exportación (summaries o items)",
    )
    parser.add_argument("--output", help="Ruta de archivo destino para exportación")

    args = parser.parse_args()

    workdir_path = Path(args.workdir).expanduser().resolve() if args.workdir else None
    config = read_config(workdir_override=workdir_path, should_create_override=False)
    setup_application_logging(config)

    parsed_date = date.fromisoformat(args.date) if args.date else None
    parsed_since = date.fromisoformat(args.since) if args.since else None
    parsed_until = date.fromisoformat(args.until) if args.until else None
    cities_list = [c.strip() for c in args.cities.split(",")] if args.cities else None
    baskets_dir_path = (
        Path(args.baskets_dir).expanduser().resolve() if args.baskets_dir else None
    )

    # Default action: if no specific mode is given, default to --evaluate
    if not (
        args.evaluate
        or args.report
        or args.list
        or args.export
        or args.html is not None
    ):
        args.evaluate = True

    if args.html is not None:
        try:
            target_out = (
                Path(args.html).expanduser().resolve()
                if args.html
                else (config.evolution_reports_dir / "evolution_latest.html")
            )
            generated_file = generate_evolution_html_report(
                config=config,
                output_path=target_out,
                basket_key=args.basket,
                since=parsed_since,
                until=parsed_until,
            )
            print(f"Reporte HTML interactivo generado en: {generated_file}")
            if args.open:
                import webbrowser

                webbrowser.open(generated_file.as_uri())
        except Exception as exc:
            logger.exception("Error al generar el reporte HTML: %s", exc)
            print(f"\n[ERROR] Fallo al generar reporte HTML: {exc}\n", file=sys.stderr)
            sys.exit(1)

    elif args.evaluate:
        try:
            result = run_basket_evolution(
                config=config,
                target_date=parsed_date,
                region=args.region,
                cities=cities_list,
                baskets_dir_override=baskets_dir_path,
            )
            print_evaluation_summary(result)
            if not result.is_success:
                sys.exit(1)
        except Exception as exc:
            logger.exception("Fallo en la evaluación de evolución de canastas: %s", exc)
            print(f"\n[ERROR] Evaluación fallida: {exc}\n", file=sys.stderr)
            sys.exit(1)

    else:
        # Analytics modes
        evolution_db_path = config.get_evolution_db_path()
        if not evolution_db_path.exists():
            print(
                f"La base de datos de evolución '{evolution_db_path}' no existe. "
                "Ejecute primero con '--evaluate' para registrar datos.",
                file=sys.stderr,
            )
            sys.exit(1)

        evo_engine = create_evolution_engine(evolution_db_path)
        with Session(evo_engine) as session:
            evo_repo = SqlAlchemyEvolutionRepository(session)
            analyzer = AnalyzeBasketEvolutionUseCase(evo_repo)

            if args.list:
                print_baskets_list(analyzer)

            elif args.report == "trend":
                if not args.basket:
                    baskets = analyzer.list_tracked_baskets()
                    if not baskets:
                        print("No hay canastas registradas.")
                        return
                    args.basket = baskets[0].basket_key
                print_trend_report(
                    analyzer=analyzer,
                    basket_key=args.basket,
                    city=args.city,
                    since=parsed_since,
                    until=parsed_until,
                )

            elif args.report == "compare":
                if not args.basket:
                    baskets = analyzer.list_tracked_baskets()
                    if not baskets:
                        print("No hay canastas registradas.")
                        return
                    args.basket = baskets[0].basket_key
                print_city_comparison_report(
                    analyzer=analyzer,
                    basket_key=args.basket,
                    target_date=parsed_date,
                )

            elif args.report == "stores":
                if not args.basket:
                    baskets = analyzer.list_tracked_baskets()
                    if not baskets:
                        print("No hay canastas registradas.")
                        return
                    args.basket = baskets[0].basket_key
                print_store_rankings_report(
                    analyzer=analyzer,
                    basket_key=args.basket,
                    city=args.city,
                    since=parsed_since,
                    until=parsed_until,
                )

            elif args.export:
                output_p = (
                    Path(args.output).expanduser().resolve() if args.output else None
                )
                export_data(
                    analyzer=analyzer,
                    format_type=args.export,
                    level=args.level,
                    basket_key=args.basket,
                    city=args.city,
                    since=parsed_since,
                    until=parsed_until,
                    output_path=output_p,
                )


if __name__ == "__main__":
    main()
