# Debugging the system

Review the following log

dberns@bluefire:~/Projects/github/DanielBerns/sur_en_precios/sur_en_precios$ uv run python -m sur_en_precios.tools.run_harvest --workdir ~/Info/sur_en_precios --file /home/dberns/Downloads/sepa_jueves.zip

==================================================
    SUR EN PRECIOS — LOCAL ARCHIVE EXTRACTED      
==================================================
 Target Date  : 2026-10-10
 Source File  : /home/dberns/Downloads/sepa_jueves.zip
 Output Dir   : /home/dberns/Info/sur_en_precios/data/raw/2026-10-10
 Extracted    : 18 files
==================================================

Following the instructions in the README.md, I run the next step to load the data in the database. Here can you see the log

dberns@bluefire:~/Projects/github/DanielBerns/sur_en_precios/sur_en_precios$ uv run python -m sur_en_precios.tools.run_etl --workdir ~/Info/sur_en_precios --region AR-U
{"timestamp": "2026-10-10 17:38:19,971", "level": "INFO", "name": "sur_en_precios", "module": "run_etl", "message": "Raw SEPA CSVs missing. Generating sample SEPA data...", "dir": "/home/dberns/Info/sur_en_precios/data/raw/2026-10-10/sepa"}
{"timestamp": "2026-10-10 17:38:19,971", "level": "INFO", "name": "sur_en_precios", "module": "process_region", "message": "Starting regional data processing ETL...", "region": "AR-U", "date": "2026-10-10", "db_path": "/home/dberns/Info/sur_en_precios/data/public.sqlite"}
{"timestamp": "2026-10-10 17:38:22,569", "level": "INFO", "name": "sur_en_precios", "module": "process_region", "message": "ETL processing completed successfully.", "stores_count": 0, "products_count": 3, "prices_count": 9}

==================================================
      SUR EN PRECIOS — ETL PIPELINE SUCCESS       
==================================================
 Region Target     : AR-U
 Date Processed    : 2026-10-10
 Database Output   : /home/dberns/Info/sur_en_precios/data/public.sqlite
 Stores Ingested   : 0
 Products Ingested : 3
 Price Records     : 9
 Reference Prices  : 3
==================================================

Why did the system ingest so little data?
