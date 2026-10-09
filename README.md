# 🛒 Sur en Precios — Supermarket Price Harvester & Optimizer

> **Clean, Hexagonal Architecture System for harvesting, processing, analyzing, and querying daily supermarket prices from Argentina's official SEPA (*Precios Claros*) dataset (`datos.produccion.gob.ar/dataset/sepa-precios`).**

---

## 🏛️ System Architecture Overview

**Sur en Precios** isolates core domain logic from framework, storage, and scraper details following **Hexagonal Architecture (Ports and Adapters)**:

- **Pure Domain Core** (`sur_en_precios.domain`): Framework-free domain models (`Product`, `Store`, `DailyPrice`, `ShoppingList`), statistical calculators (Reference Price via Geometric Mean, Price Dispersion, percentage variations), and multi-store basket optimization.
- **Driving Adapters** (`sur_en_precios.web` & `sur_en_precios.tools`): Public Web Portal (`public_app`), Private Admin Control Dashboard (`control_app`), and CLI tools (`run_etl`, `log_analyzer`).
- **Driven Adapters** (`sur_en_precios.adapters`): Async HTTP scraper using `aiohttp`, storage adapter using `pathlib.Path`, SQLAlchemy 2.0 ORM repositories with SQLite FTS5 search, and structured JSON logger with `RotatingFileHandler`.

---

## ⚡ Requirements & Prerequisites

- **Python 3.12+**
- **`uv`** (fast Python package and project manager)

To verify `uv` installation:
```bash
uv --version
```
If missing, install `uv` via:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## ⚙️ Installation

Clone the repository and install all dependencies in the local virtual environment using `uv`:

```bash
cd sur_en_precios
uv sync
```

This automatically locks dependencies and installs the `sur-en-precios` package in editable mode.

---

## 🔧 Configuration

The application resolves its working directory and configuration dynamically using a 3-tier hierarchy:

1. **CLI Argument**: `--workdir /path/to/workdir`
2. **Environment Variable**: `WORKING_DIRECTORY=/path/to/workdir`
3. **Fallback Default**: `~/Info/sur_en_precios`

### Generating Configuration (`config.yaml`)

Run any tool with the `--create` flag to generate the default `config.yaml` file inside the working directory:

```bash
uv run python -m sur_en_precios.tools.run_etl --create
```

### Configuration Schema (`config.yaml`)

```yaml
app:
  name: "Sur en Precios"
  region: "AR-B"               # ISO 3166-2 Argentine Province Code (e.g. AR-B for Buenos Aires)
  debug: false

database:
  public_db_filename: "public.sqlite"      # Daily swapped region price DB
  user_db_filename: "user_data.sqlite"   # User accounts & saved shopping lists DB
  control_db_filename: "control.sqlite"   # System execution & audit logs DB

scraper:
  sepa_url: "https://datos.produccion.gob.ar/dataset/sepa-precios"
  raw_storage_dir: "data/raw"
  timeout_seconds: 120

logging:
  level: "INFO"
  log_dir: "logs"
  max_bytes: 10485760          # 10MB rotation
  backup_count: 5
```

---

## 🚀 Running the System

### 1. Execute the Regional Data Ingestion & ETL Pipeline

Processes SEPA CSV archives, calculates integer Pesos prices & Geometric Mean Reference Prices, and builds `public.sqlite` with SQLite FTS5 full-text indexing:

```bash
# Run for target region (e.g., AR-B for Buenos Aires)
uv run python -m sur_en_precios.tools.run_etl --region AR-B

# Specify explicit working directory and processing date
uv run python -m sur_en_precios.tools.run_etl --workdir ./my_workdir --region AR-B --date 2026-10-09
```

### 2. Launch the Public Web Portal

Web interface localized in Argentine Spanish (`es_AR`) providing product search, saved shopping lists, and interactive basket price optimization:

```bash
uv run python -m sur_en_precios.web.public_app.app
```
Open browser at: `http://localhost:5000`

### 3. Launch the Private Admin Control Dashboard

Private dashboard with Basic Authentication monitoring ETL job execution status, file sizes, and errors:

```bash
uv run python -m sur_en_precios.web.control_app.app
```
Open browser at: `http://localhost:5001`  
*(Default Credentials: `admin` / `sur_precios_2026`)*

### 4. Query Execution Logs using Structured Log Analyzer

Query, filter, and summarize structured JSON execution logs recorded in `logs/sur_en_precios.log.json`:

```bash
# View summary count by severity level
uv run python -m sur_en_precios.tools.log_analyzer --summary

# Filter logs by severity level
uv run python -m sur_en_precios.tools.log_analyzer --level ERROR

# Search log messages
uv run python -m sur_en_precios.tools.log_analyzer --search "ETL"
```

---

## 🧪 Testing & Code Quality Assurance

Run the quality suite using `uv`:

```bash
# 1. Linting & Import Sorting Check
uv run ruff check .

# 2. Code Formatting Check
uv run ruff format --check .

# 3. Static Type Analysis
uv run mypy src/

# 4. Automated Pytest Test Suite
uv run pytest
```

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for details.
