# Implementation Plan — "Sur en Precios"

This document outlines the step-by-step technical implementation plan for constructing the **"Sur en Precios"** system. The implementation adheres strictly to **Hexagonal Architecture (Ports and Adapters)**, **SQLAlchemy 2.0+ ORM standards**, **`uv` package management**, **`pathlib.Path` file operations**, **structured JSON logging**, and **Argentine Spanish (`es_AR`) UI internationalization**.

---

## User Review Required

> [!IMPORTANT]
> **Strict Python & Architecture Constraints Checklist**:
> 1. **SQLAlchemy 2.0+ Only**: Direct SQL string embedding is strictly banned. All queries use SQLAlchemy ORM model mappings and `select(...)` statements.
> 2. **`pathlib.Path` Only**: `os.path` and `os.makedirs` are strictly banned.
> 3. **`aiohttp` Only**: `httpx` and `requests` are strictly banned for scraper HTTP calls.
> 4. **Data & Code Separation**: Databases (`public.sqlite`, `user_data.sqlite`, `control.sqlite`) and raw SEPA datasets MUST NOT be stored in code directories. All data paths live outside the codebase repository in the dynamically resolved `--workdir` path.
> 5. **Reference Price Terminology**: The geometric mean of product prices across stores is named **"Reference Price"** (**"Precio de Referencia"** in Spanish / `reference_price` in domain code).
> 6. **Language & i18n**: Codebase (variables, functions, comments) developed 100% in **English**. User Interface developed in **Argentine Spanish (`es_AR`)** with Flask-Babel (zero hardcoded strings).
> 7. **Prices in Integer Pesos**: All prices stored and displayed in integer Pesos Argentinos ($ARS$) without cents.
> 8. **Package Manager**: All dependencies managed via `uv` in `pyproject.toml` and `.venv`.

---

## Proposed Changes

Work will be executed in **5 logical phases**, creating modular components with comprehensive Pytest coverage.

---

### Phase 1: Pure Domain Core & Configuration Module

Establish the framework-agnostic domain models, business logic calculators, configuration parser, and abstract ports.

#### [NEW] [config.py](file:///home/dberns/Downloads/AI-course-main/sur_en_precios/src/sur_en_precios/config.py)
- Implement `AppConfig` Pydantic schema (`AppSettings`, `DatabaseSettings`, `ScraperSettings`, `LoggingSettings`).
- Implement `resolve_working_directory()` checking CLI `--workdir`, `WORKING_DIRECTORY` env var, and default `~/Info/sur_en_precios/`.
- Implement `read_config()` with `--create` flag support to generate `config.yaml` automatically.

#### [NEW] [domain/models.py](file:///home/dberns/Downloads/AI-course-main/sur_en_precios/src/sur_en_precios/domain/models.py)
- Pure Python dataclasses for `Product`, `Store`, `Price`, `ShoppingList`, `ListItem`, `BasketOptimizationResult`, and `DailyMetrics`.

#### [NEW] [domain/services.py](file:///home/dberns/Downloads/AI-course-main/sur_en_precios/src/sur_en_precios/domain/services.py)
- `BasketOptimizerService`: Computes best single store total, item-by-item cheapest allocation, and partial basket availability match handling.
- `PriceMetricsCalculator`: Computes $P_{min}$, $P_{max}$, $P_{median}$, Geometric Mean $P_{geo} = \exp\left(\frac{1}{n}\sum \ln P_i\right)$, price dispersion index, and 7d/30d/90d percentage variations.

#### [NEW] [domain/ports.py](file:///home/dberns/Downloads/AI-course-main/sur_en_precios/src/sur_en_precios/domain/ports.py)
- Abstract Base Classes (ABCs) for `ScraperPort`, `RawStoragePort`, `CatalogRepositoryPort`, `PriceRepositoryPort`, and `UserRepositoryPort`.

---

### Phase 2: Driven Adapters (SQLAlchemy 2.0+, `aiohttp`, Storage, & Logging)

Implement concrete infrastructure adapters.

#### [NEW] [adapters/logging.py](file:///home/dberns/Downloads/AI-course-main/sur_en_precios/src/sur_en_precios/adapters/logging.py)
- Structured JSON logging setup using `python-json-logger` alongside `RotatingFileHandler` writing to `logs/sur_en_precios.log.json`.

#### [NEW] [tools/log_analyzer.py](file:///home/dberns/Downloads/AI-course-main/sur_en_precios/src/sur_en_precios/tools/log_analyzer.py)
- CLI utility script to search, filter, and summarize structured JSON logs by severity level, event type, and date range.

#### [NEW] [adapters/storage.py](file:///home/dberns/Downloads/AI-course-main/sur_en_precios/src/sur_en_precios/adapters/storage.py)
- `FileSystemStorageAdapter`: Manages raw daily SEPA archive downloads using `pathlib.Path` exclusively.

#### [NEW] [adapters/harvester.py](file:///home/dberns/Downloads/AI-course-main/sur_en_precios/src/sur_en_precios/adapters/harvester.py)
- `AiohttpScraperAdapter`: Asynchronous HTTP scraper for `datos.produccion.gob.ar/dataset/sepa-precios` using `aiohttp.ClientSession`.

#### [NEW] [adapters/database/models_user.py](file:///home/dberns/Downloads/AI-course-main/sur_en_precios/src/sur_en_precios/adapters/database/models_user.py)
- SQLAlchemy 2.0 Declarative models (`UserModel`, `ShoppingListModel`, `ListItemModel`) mapped to `user_data.sqlite`.

#### [NEW] [adapters/database/models_public.py](file:///home/dberns/Downloads/AI-course-main/sur_en_precios/src/sur_en_precios/adapters/database/models_public.py)
- SQLAlchemy 2.0 Declarative models (`ProductModel`, `StoreModel`, `DailyPriceModel`, `DailyProductMetricModel`) mapped to `public.sqlite`.

#### [NEW] [adapters/database/repositories.py](file:///home/dberns/Downloads/AI-course-main/sur_en_precios/src/sur_en_precios/adapters/database/repositories.py)
- Concrete SQLAlchemy repositories implementing domain repository ports using 2.0 `select(...)` and `execute(...)` APIs.

---

### Phase 3: Application Use Cases (ETL & Operations)

Implement business use cases orchestrating domain services and ports.

#### [NEW] [use_cases/harvest_data.py](file:///home/dberns/Downloads/AI-course-main/sur_en_precios/src/sur_en_precios/use_cases/harvest_data.py)
- Downloads daily `sepa.zip` archive, unpacks `comercio.csv`, `sucursales.csv`, `productos.csv`, and reports execution metrics to Component 2 API.

#### [NEW] [use_cases/process_region.py](file:///home/dberns/Downloads/AI-course-main/sur_en_precios/src/sur_en_precios/use_cases/process_region.py)
- Parses pipe-delimited CSVs via DuckDB, calculates integer Pesos prices & geometric mean metrics, builds regional `public_<region>.sqlite` via SQLAlchemy 2.0 ORM, and performs atomic SFTP/SSH deployment.

#### [NEW] [use_cases/optimize_basket.py](file:///home/dberns/Downloads/AI-course-main/sur_en_precios/src/sur_en_precios/use_cases/optimize_basket.py)
- Executes basket price search, store price matrix generation with green/red/geometric mean badges, and single store vs item-by-item optimal breakdown.

---

### Phase 4: Flask Web Applications (Sites 2 & 4)

Construct light Flask applications with HTML5 + Vanilla JS/CSS and Flask-Babel `es_AR` i18n.

#### [NEW] [web/control_app/app.py](file:///home/dberns/Downloads/AI-course-main/sur_en_precios/src/sur_en_precios/web/control_app/app.py)
- Private control website with Basic Auth, dashboard table showing scraper/ETL run logs, file sizes, execution times, error alerts, and API logging endpoints (`/api/logs/scraper`, `/api/logs/processor`).

#### [NEW] [web/public_app/app.py](file:///home/dberns/Downloads/AI-course-main/sur_en_precios/src/sur_en_precios/web/public_app/app.py)
- Public user portal with Flask-Babel (`es_AR`), user registration/login, indexed product search with facets, saved shopping lists, interactive basket price optimizer, store price matrix grid, and price evolution charts.

#### [NEW] [web/public_app/translations/es_AR/LC_MESSAGES/messages.po](file:///home/dberns/Downloads/AI-course-main/sur_en_precios/src/sur_en_precios/web/public_app/translations/es_AR/LC_MESSAGES/messages.po)
- Spanish translation catalog covering all UI labels, button texts, table headers, and status badges.

---

### Phase 5: Automated Testing Suite

Build comprehensive Pytest unit and integration tests.

#### [NEW] [tests/unit/test_config.py](file:///home/dberns/Downloads/AI-course-main/sur_en_precios/tests/unit/test_config.py)
- Tests CLI `--workdir`, environment variable precedence, and `--create` YAML file generation.

#### [NEW] [tests/unit/test_basket_optimizer.py](file:///home/dberns/Downloads/AI-course-main/sur_en_precios/tests/unit/test_basket_optimizer.py)
- Unit tests for single store optimal basket cost, item-by-item optimal allocation, geometric mean threshold calculations, and partial match handling.

#### [NEW] [tests/unit/test_metrics_calculator.py](file:///home/dberns/Downloads/AI-course-main/sur_en_precios/tests/unit/test_metrics_calculator.py)
- Tests for min, max, median, geometric mean, price dispersion, and 7d/30d/90d percentage variation calculation logic.

#### [NEW] [tests/integration/test_sqlalchemy_repos.py](file:///home/dberns/Downloads/AI-course-main/sur_en_precios/tests/integration/test_sqlalchemy_repos.py)
- Integration tests verifying SQLAlchemy 2.0 models and repository methods against temporary SQLite databases.

#### [NEW] [tests/integration/test_aiohttp_harvester.py](file:///home/dberns/Downloads/AI-course-main/sur_en_precios/tests/integration/test_aiohttp_harvester.py)
- Integration tests using a mock HTTP server to test `AiohttpScraperAdapter` downloading and error handling.

---

## Verification Plan

### Automated Tests
Run quality assurance checks from the project root:
```bash
# 1. Linting & Formatting Check
uv run ruff check .
uv run ruff format --check .

# 2. Static Type Checking
uv run mypy src/

# 3. Test Suite Execution
uv run pytest
```

### Manual Verification
1. **Scraper Harvester**: Execute `HarvestDailyDataUseCase` against sample SEPA test files and verify raw `.zip` extraction under `data/raw/`.
2. **ETL Processor**: Run `ProcessAndPublishRegionUseCase` to generate `public.sqlite` and verify that prices are stored as integer Pesos Argentinos and database schema matches SQLAlchemy ORM.
3. **Web Applications**: Launch Flask public app and verify:
   - UI text rendered in Argentine Spanish (`es_AR`) with zero missing translation keys.
   - Product search returns fast matches.
   - Basket optimizer highlights lowest price (green), highest price (red), and geometric mean threshold.
   - Private control panel displays scraper audit logs.
