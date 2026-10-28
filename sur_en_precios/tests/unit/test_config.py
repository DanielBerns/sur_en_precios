from pathlib import Path

import pytest

from sur_en_precios.config import read_config


def test_read_config_with_create_flag(tmp_path: Path) -> None:
    workdir = tmp_path / "test_app"
    config = read_config(workdir_override=workdir, should_create_override=True)

    assert config.workdir == workdir
    assert config.get_app_name() == "Sur en Precios"
    assert config.get_region() == "AR-U"
    assert (workdir / "config.yaml").exists()
    assert (workdir / "data").exists()
    assert (workdir / "logs").exists()


def test_read_config_missing_raises_error(tmp_path: Path) -> None:
    workdir = tmp_path / "missing_app"
    with pytest.raises(FileNotFoundError) as exc_info:
        read_config(workdir_override=workdir, should_create_override=False)
    assert "sur_en_precios.tools.start" in str(exc_info.value)
