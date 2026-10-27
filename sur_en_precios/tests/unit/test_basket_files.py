"""Unit tests for loading downloaded benchmark baskets from directory and YAML files."""

from pathlib import Path

from sur_en_precios.adapters.basket_files import (
    load_basket_file,
    load_baskets_from_directory,
)


def test_load_basket_file_valid(tmp_path: Path) -> None:
    yaml_content = """# Basket export
version: "1.0"
basket:
  name: "CBA Test"
  uuid: "test-uuid-1234"
  items:
    - ean: "779001"
      quantity: 2
      numerator: 1
      denominator: 1
      selected: true
      name: "Milk"
    - ean: "779002"
      quantity: 1
      selected: false
"""
    file_path = tmp_path / "cba.yaml"
    file_path.write_text(yaml_content, encoding="utf-8")

    spec = load_basket_file(file_path)
    assert spec.key == "test-uuid-1234"
    assert spec.name == "CBA Test"
    assert len(spec.items) == 1  # Only selected item is loaded
    assert spec.items[0].ean == "779001"
    assert spec.items[0].quantity == 2


def test_load_basket_file_fallback_key_to_stem(tmp_path: Path) -> None:
    yaml_content = """
version: "1.0"
basket:
  name: "Custom Basket"
  items:
    - ean: "779001"
      quantity: 1
      selected: true
"""
    file_path = tmp_path / "Mi Canasta Familiar.yaml"
    file_path.write_text(yaml_content, encoding="utf-8")

    spec = load_basket_file(file_path)
    assert spec.key == "mi-canasta-familiar"
    assert spec.name == "Custom Basket"


def test_load_baskets_from_directory_with_errors_isolated(tmp_path: Path) -> None:
    # 1. Valid basket
    (tmp_path / "good.yaml").write_text(
        """version: "1.0"
basket:
  name: "Good"
  uuid: "uuid-good"
  items:
    - ean: "779001"
      quantity: 1
""",
        encoding="utf-8",
    )

    # 2. Corrupt YAML
    (tmp_path / "corrupt.yaml").write_text("invalid: yaml: [", encoding="utf-8")

    # 3. No items
    (tmp_path / "empty.yaml").write_text(
        """version: "1.0"
basket:
  name: "Empty"
  items: []
""",
        encoding="utf-8",
    )

    results = load_baskets_from_directory(tmp_path)
    assert len(results) == 3

    ok_results = [r for r in results if r.ok]
    err_results = [r for r in results if not r.ok]

    assert len(ok_results) == 1
    assert ok_results[0].spec is not None
    assert ok_results[0].spec.key == "uuid-good"

    assert len(err_results) == 2


def test_load_baskets_from_nonexistent_directory(tmp_path: Path) -> None:
    results = load_baskets_from_directory(tmp_path / "nonexistent")
    assert results == []
