"""Unit tests for retail taxonomy and classifier."""

from sur_en_precios.domain.cleaner.article_cleaner import CleanedArticleData
from sur_en_precios.domain.taxonomy.categories import DEFAULT_TAXONOMY, get_taxonomy_map
from sur_en_precios.domain.taxonomy.classifier import TaxonomyClassifier


def test_taxonomy_definitions():
    tax_map = get_taxonomy_map()
    assert "Almacén" in tax_map
    assert "Bebidas" in tax_map
    assert "Lácteos y Frescos" in tax_map
    assert "Limpieza" in tax_map
    assert "Perfumería y Cuidado Personal" in tax_map
    assert "Electro, Bazar y Hogar" in tax_map

    # Check level 1 vs 2
    for dept in DEFAULT_TAXONOMY:
        assert dept.name
        assert dept.slug
        assert len(dept.subcategories) > 0
        for sub in dept.subcategories:
            assert sub.name
            assert sub.slug


def test_classifier_beverages():
    classifier = TaxonomyClassifier()

    # Red Wine
    art_wine = CleanedArticleData(
        ean="7790040001001",
        name="Vino Tinto Malbec Rutini 750 ml",
        clean_description="vino tinto malbec",
        raw_description="vino tinto malbec rutini 750 cc",
        brand_name="Rutini",
        package="750 ml",
        package_amount=750.0,
        package_unit="ml",
    )
    res_wine = classifier.classify(art_wine)
    assert res_wine.department == "Bebidas"
    assert res_wine.subcategory == "Vinos Tintos"
    assert "malbec" in res_wine.tags

    # Water
    art_water = CleanedArticleData(
        ean="7790040001002",
        name="Agua Mineral Sin Gas Villavicencio 1.5 L",
        clean_description="agua mineral sin gas",
        raw_description="agua mineral sin gas villavicencio 1.5 lt",
        brand_name="Villavicencio",
        package="1.5 L",
        package_amount=1.5,
        package_unit="L",
    )
    res_water = classifier.classify(art_water)
    assert res_water.department == "Bebidas"
    assert res_water.subcategory == "Aguas y Aguas Saborizadas"
    assert "sin gas" in res_water.tags


def test_classifier_dairy_and_grocery():
    classifier = TaxonomyClassifier()

    # Milk
    art_milk = CleanedArticleData(
        ean="7790040001003",
        name="Leche Entera La Serenísima 1 L",
        clean_description="leche entera",
        raw_description="leche entera sachet la serenisima 1 lt",
        brand_name="La Serenísima",
        package="1 L",
        package_amount=1.0,
        package_unit="L",
    )
    res_milk = classifier.classify(art_milk)
    assert res_milk.department == "Lácteos y Frescos"
    assert res_milk.subcategory == "Leches"
    assert "entera" in res_milk.tags

    # Olive Oil
    art_oil = CleanedArticleData(
        ean="7790040001004",
        name="Aceite de Oliva Extra Virgen Zuelo 500 ml",
        clean_description="aceite de oliva extra virgen",
        raw_description="aceite de oliva extra virgen zuelo 500 ml",
        brand_name="Zuelo",
        package="500 ml",
        package_amount=500.0,
        package_unit="ml",
    )
    res_oil = classifier.classify(art_oil)
    assert res_oil.department == "Almacén"
    assert res_oil.subcategory == "Aceites y Vinagres"
    assert "extra virgen" in res_oil.tags


def test_classifier_personal_care_and_cleaning():
    classifier = TaxonomyClassifier()

    # Shampoo
    art_shampoo = CleanedArticleData(
        ean="7790040001005",
        name="Shampoo Bomba de Nutrición Sedal 340 ml",
        clean_description="shampoo bomba de nutricion",
        raw_description="shampoo sedal bomba de nutricion 340 ml",
        brand_name="Sedal",
        package="340 ml",
        package_amount=340.0,
        package_unit="ml",
    )
    res_shampoo = classifier.classify(art_shampoo)
    assert res_shampoo.department == "Perfumería y Cuidado Personal"
    assert res_shampoo.subcategory == "Cuidado Capilar"

    # Bleach
    art_bleach = CleanedArticleData(
        ean="7790040001006",
        name="Lavandina Común Ayudín 1 L",
        clean_description="lavandina comun",
        raw_description="lavandina ayudin clasica 1 lt",
        brand_name="Ayudín",
        package="1 L",
        package_amount=1.0,
        package_unit="L",
    )
    res_bleach = classifier.classify(art_bleach)
    assert res_bleach.department == "Limpieza"
    assert res_bleach.subcategory == "Limpieza de Baño y Desinfección"
