from sur_en_precios.domain.normalizers import (
    decode_region_code,
    normalize_brand,
    normalize_city,
    normalize_description,
    to_spanish_title,
)


def test_decode_region_code():
    assert decode_region_code("AR-U") == "Chubut"
    assert decode_region_code("AR-B") == "Buenos Aires"
    assert decode_region_code("AR-C") == "Ciudad Autónoma de Buenos Aires"
    assert decode_region_code("AR-X") == "Córdoba"
    assert decode_region_code("ar-u") == "Chubut"
    assert decode_region_code("UNKNOWN") == "UNKNOWN"
    assert decode_region_code("") == "Buenos Aires"


def test_normalize_city():
    # Capital letter variations deduplication
    assert normalize_city("TRELEW") == "Trelew"
    assert normalize_city("Trelew") == "Trelew"
    assert normalize_city("trelew") == "Trelew"

    assert normalize_city("PUERTO MADRYN") == "Puerto Madryn"
    assert normalize_city("Puerto Madryn") == "Puerto Madryn"

    assert normalize_city("COMODORO RIVADAVIA") == "Comodoro Rivadavia"
    assert normalize_city("Comodoro Rivadavia") == "Comodoro Rivadavia"

    # Accents handling
    assert normalize_city("Playa Union") == "Playa Unión"
    assert normalize_city("PLAYA UNION") == "Playa Unión"
    assert normalize_city("Bahia Blanca") == "Bahía Blanca"
    assert normalize_city("BAHIA BLANCA") == "Bahía Blanca"

    # Prepositions in Spanish
    assert normalize_city("SAN MIGUEL DE TUCUMAN") == "San Miguel de Tucumán"

    # Fallbacks and whitespace
    assert normalize_city("  Esquel\xa0 ") == "Esquel"
    assert normalize_city("") == "General"
    assert normalize_city(None) == "General"


def test_normalize_brand():
    assert normalize_brand("LIVENZA") == "Livenza"
    assert normalize_brand("CARREFOUR CLASSIC") == "Carrefour Classic"
    assert normalize_brand("STURLA\xa0") == "Sturla"
    assert normalize_brand("STURLA") == "Sturla"
    assert normalize_brand("LA PLANTA DE CAFé.") == "La Planta de Café"
    assert normalize_brand("YPF") == "YPF"
    assert normalize_brand("3M") == "3M"
    assert normalize_brand("") == "Sin Marca"
    assert normalize_brand("S/M") == "Sin Marca"
    assert normalize_brand("SIN MARCA") == "Sin Marca"


def test_normalize_description_and_brand_demangling():
    # Brand de-mangling
    desc = normalize_description("LENTEJON OLINTO", brand="OLINTO")
    assert desc == "Lentejón" or desc == "Lentejon"

    desc2 = normalize_description("ARROZ DOBLE MOCOVI CAJA", brand="MOCOVI")
    assert "Mocovi" not in desc2
    assert "Arroz Doble" in desc2

    # Diacritics matching (Canuelas vs Cañuelas)
    desc3 = normalize_description("ACEITE GIRASOL CANUELAS", brand="CAÑUELAS")
    assert "Canuelas" not in desc3
    assert "Aceite Girasol" in desc3

    # Preserves description when brand is not in description
    desc4 = normalize_description("LECHE ENTERA 1L", brand="LA SERENISIMA")
    assert "Leche Entera" in desc4

    # Spanish lowercase prepositions
    assert to_spanish_title("DULCE DE LECHE") == "Dulce de Leche"
    assert to_spanish_title("ACEITE CON VITAMINA") == "Aceite con Vitamina"
    assert to_spanish_title("GALLETITAS SIN SAL") == "Galletitas sin Sal"
