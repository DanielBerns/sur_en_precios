#!/usr/bin/env bash

cd ~/Apps/sur_en_precios/sur_en_precios
uv run python -m sur_en_precios.tools.run_daily_update --workdir ~/Info/sur_en_precios
