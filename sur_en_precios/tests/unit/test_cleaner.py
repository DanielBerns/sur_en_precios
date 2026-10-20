"""Unit tests for the cleaner subpackage (text_utils, package_parser, brand_cleaner, article_cleaner)."""

import pytest

from sur_en_precios.domain.cleaner.article_cleaner import ArticleCleaner
from sur_en_precios.domain.cleaner.brand_cleaner import BrandLexicon, clean_brand_name
from sur_en_precios.domain.cleaner.package_parser import parse_package
from sur_en_precios.domain.cleaner.text_utils import (
    clean_whitespace,
    normalize_nfc,
    slugify,
    strip_accents,
    title_case_spanish,
)


def test_normalize_nfc():
    # Decomposed NFD form
    nfd = "can\u0303uelas"
    assert normalize_nfc(nfd) == "cañuelas"
    assert normalize_nfc("  aceite  ") == "aceite"
    assert normalize_nfc(None) == ""


def test_strip_accents():
    assert strip_accents("cañuelas") == "canuelas"
    assert strip_accents("té limón") == "te limon"
    assert strip_accents(None) == ""


def test_title_case_spanish():
    assert title_case_spanish("aceite de oliva extra virgen") == "Aceite de Oliva Extra Virgen"
    assert title_case_spanish("arroz con leche la serenisima") == "Arroz con Leche la Serenisima"
    assert title_case_spanish("vino tinto malbec") == "Vino Tinto Malbec"


def test_slugify():
    assert slugify("Aceites y Vinagres") == "aceites-y-vinagres"
    assert slugify("Vino Tinto Malbec 2020!") == "vino-tinto-malbec-2020"


def test_package_parser():
    # Milliliters
    p1 = parse_package("500.0 ml")
    assert p1.amount == 500.0
    assert p1.unit == "ml"
    assert p1.display == "500 ml"

    # Cubic centimeters -> ml
    p2 = parse_package("250.0 cc")
    assert p2.amount == 250.0
    assert p2.unit == "ml"
    assert p2.display == "250 ml"

    # Liters
    p3 = parse_package("1.5 lt")
    assert p3.amount == 1.5
    assert p3.unit == "L"
    assert p3.display == "1.5 L"

    # Grams
    p4 = parse_package("75.0 gr")
    assert p4.amount == 75.0
    assert p4.unit == "g"
    assert p4.display == "75 g"

    # Kilograms
    p5 = parse_package("1.0 kg")
    assert p5.amount == 1.0
    assert p5.unit == "kg"
    assert p5.display == "1 kg"

    # Units
    p6 = parse_package("12.0 un")
    assert p6.amount == 12.0
    assert p6.unit == "u"
    assert p6.display == "12 u"

    # Meters
    p7 = parse_package("50.0 mt")
    assert p7.amount == 50.0
    assert p7.unit == "m"
    assert p7.display == "50 m"

    # None
    assert parse_package(None).display is None


def test_brand_cleaner():
    assert clean_brand_name("  hawaian  ") == "Hawaian"
    assert clean_brand_name("la anónima") == "La Anónima"
    assert clean_brand_name("molino cañuelas ") == "Molino Cañuelas"
    assert clean_brand_name("sin marca") is None
    assert clean_brand_name("sinn marca") is None
    assert clean_brand_name("SIN MARCA ") is None
    assert clean_brand_name(None) is None


def test_article_cleaner_tagged_article():
    cleaner = ArticleCleaner()
    # Tagged article
    res = cleaner.process(
        ean="7790272001029",
        raw_description="aceite de girasol natura 1.5 lt",
        raw_brand="natura",
        raw_package="1.5 lt",
        raw_tags=["aceite de girasol"],
    )
    assert res.ean == "7790272001029"
    assert res.brand_name == "Natura"
    assert res.package == "1.5 L"
    assert res.clean_description == "aceite de girasol"
    assert res.name == "Aceite de Girasol Natura 1.5 L"
    assert "aceite de girasol" in res.tags


def test_article_cleaner_untagged_articles():
    lexicon = BrandLexicon(["la anónima", "la anonima", "molino cañuelas", "cañuelas"])
    cleaner = ArticleCleaner(brand_lexicon=lexicon)

    # 1. Untagged olive oil
    res1 = cleaner.process(
        ean="7792180005229",
        raw_description="aceite de oliva intenso cañuelas 500 ml",
        raw_brand="cañuelas",
        raw_package="500.0 ml",
        raw_tags=[],
    )
    assert res1.clean_description == "aceite de oliva intenso"
    assert res1.brand_name == "Cañuelas"
    assert res1.package == "500 ml"
    assert "Aceite de Oliva Intenso" in res1.name

    # 2. Untagged store brand peas
    res2 = cleaner.process(
        ean="7798158707577",
        raw_description="arvejas la anonima 400 gr",
        raw_brand="la anónima",
        raw_package="400.0 gr",
        raw_tags=[],
    )
    assert res2.clean_description == "arvejas"
    assert res2.brand_name == "La Anónima"
    assert res2.package == "400 g"

    # 3. Untagged conditioner
    res3 = cleaner.process(
        ean="7798140253839",
        raw_description="acondicionador aclarante recargabler doypack tio nacho 400 ml",
        raw_brand="tío nacho",
        raw_package="400.0 ml",
        raw_tags=[],
    )
    assert "acondicionador aclarante recargabler doypack" in res3.clean_description
    assert res3.brand_name == "Tío Nacho"
    assert res3.package == "400 ml"
