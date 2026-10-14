# 🛒 Sur en Precios — Supermarket Price Harvester & Optimizer

> **Clean, Hexagonal Architecture System for harvesting, processing, analyzing, and querying daily supermarket prices from Argentina's official SEPA (*Precios Claros*) dataset (`datos.produccion.gob.ar/dataset/sepa-precios`).**

---

## 🏛️ System Architecture Overview

**Sur en Precios** isolates core domain logic from framework, storage, and scraper details following **Hexagonal Architecture (Ports and Adapters)**:

- **Pure Domain Core** (`sur_en_precios.domain`): Framework-free domain models (`Product`, `Store`, `DailyPrice`, `ShoppingList`), statistical calculators (Reference Price via Geometric Mean, Price Dispersion, percentage variations), and multi-store basket optimization.
- **Driving Adapters** (`sur_en_precios.web` & `sur_en_precios.tools`): Public Web Portal (`public_app`), Private Admin Control Dashboard (`control_app`), and CLI tools (`run_harvest`, `run_etl`, `log_analyzer`).
- **Driven Adapters** (`sur_en_precios.adapters`): Async HTTP scraper using `aiohttp`, storage adapter using `pathlib.Path`, SQLAlchemy 2.0 ORM repositories with indexed search, and structured JSON logger with `RotatingFileHandler`.

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

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

Clone the repository and install all dependencies in the local virtual environment using `uv`:

```bash
git clone https://github.com/DanielBerns/sur_en_precios.git
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
  region: "AR-U"               # ISO 3166-2 Argentine Province Code (e.g. AR-U for Chubut, AR-B for Buenos Aires)
  debug: false

database:
  public_db_filename: "public.sqlite"      # Daily swapped region price DB
  user_db_filename: "user_data.sqlite"   # User accounts & saved shopping lists DB
  control_db_filename: "control.sqlite"   # System execution & audit logs DB

etl:
  generate_sample_data: false   # Feature flag: set true to generate mock CSVs when raw SEPA data is missing
  insert_batch_size: 10000      # Rows per bulk upsert batch
  temp_dir: "data/tmp"          # Directory for temporary extraction

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

## ⚙️ Initialization

No initialization steps required. Database tables are automatically initialized on first ETL run.

---

## 🚀 Execution

### 1. Data Harvesting (Online Web Portal or Local Archives)

Scrape and harvest daily dataset archives from the official SEPA website (`https://datos.produccion.gob.ar/dataset/sepa-precios`) or ingest local archives:

```bash
# Online mode: downloads the SEPA dataset webpage, scans for new zip archives, and downloads them automatically
uv run python -m sur_en_precios.tools.run_harvest

# Specify a custom working directory or create default configuration
uv run python -m sur_en_precios.tools.run_harvest --workdir ~/Info/sur_en_precios --create
```

New remote archives are identified by comparing discovered dates against existing archives in `data/raw/`. Discovered archives are automatically downloaded, verified, and stored as `data/raw/<YYYY-MM-DD>/sepa_<YYYY-MM-DD>.zip` and extracted to `data/raw/<YYYY-MM-DD>/sepa_<YYYY-MM-DD>/`.

For offline mode, set `scraper.local_archive_file` in `config.yaml` to process a local `.zip` file.

### 2. Execute Regional Data Ingestion & ETL Pipeline

Processes nested chain CSV archives, filters stores by region, joins prices, computes integer Pesos prices & Geometric Mean Reference Prices, and builds `public.sqlite` managed entirely via SQLAlchemy 2.0 ORM:

```bash
# Run for configured region (reads region from config.yaml, e.g. AR-U)
uv run python -m sur_en_precios.tools.run_etl

# Run for specific region code or processing date
uv run python -m sur_en_precios.tools.run_etl --region AR-U --date 2026-10-01
```

### 3. Launch the Public Web Portal

Web interface localized in Argentine Spanish (`es_AR`) providing product search, saved shopping lists, and interactive basket price optimization:

```bash
uv run python -m sur_en_precios.web.public_app.app
```
Open browser at: `http://localhost:5000`

### 4. Launch the Private Admin Control Dashboard

Private dashboard with Basic Authentication monitoring ETL job execution status, file sizes, and errors:

```bash
uv run python -m sur_en_precios.web.control_app.app
```
Open browser at: `http://localhost:5001`  
*(Default Credentials: `admin` / `sur_precios_2026`)*

### 5. Query Execution Logs using Structured Log Analyzer

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
