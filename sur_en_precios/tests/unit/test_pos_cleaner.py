"""Unit and integration tests for Point of Sale (POS) cleaner module."""

from hermes_reborn.models import Base, PointOfSale
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from sur_en_precios.domain.cleaner.pos_cleaner import (
    clean_address,
    clean_branch,
    clean_point_of_sale_record,
    decompose_pos_code,
    resolve_corporate_info,
    resolve_geographic_info,
)


def test_decompose_pos_code_valid():
    cid, bid, sid, slug, sepa_id = decompose_pos_code("(11-2-1075)(changomas)")
    assert cid == 11
    assert bid == 2
    assert sid == 1075
    assert slug == "changomas"
    assert sepa_id == "11-2-1075"


def test_decompose_pos_code_invalid():
    cid, bid, sid, slug, sepa_id = decompose_pos_code("invalid_code")
    assert cid is None
    assert bid is None
    assert sid is None
    assert slug is None
    assert sepa_id is None


def test_resolve_corporate_info():
    # Carrefour
    biz, group, brand, fmt = resolve_corporate_info(10, 3)
    assert biz == "INC S.A."
    assert group == "Carrefour Group"
    assert brand == "Carrefour Express"
    assert fmt == "Proximidad"

    # GDN Argentina / ex-Walmart
    biz, group, brand, fmt = resolve_corporate_info(11, 2)
    assert "GDN Argentina" in biz
    assert brand == "ChangoMás"
    assert fmt == "Supermercado"

    # Cencosud / Vea
    biz, group, brand, fmt = resolve_corporate_info(9, 1)
    assert group == "Cencosud"
    assert brand == "Vea"

    # Farmacity
    biz, group, brand, fmt = resolve_corporate_info(24, 1)
    assert group == "Grupo Pegasus"
    assert brand == "Farmacity"
    assert fmt == "Farmacia"

    # Simplicity
    biz, group, brand, fmt = resolve_corporate_info(24, 3)
    assert brand == "Simplicity"


def test_clean_address():
    # Strip none and standardise Av.
    addr1 = clean_address("avenida fuerza aerea esq. aguas blancas none")
    assert addr1 == "Av. Fuerza Aerea esq. Aguas Blancas"

    # Strip trailing 0
    addr2 = clean_address("20 de febrero esq. guemes 0")
    assert addr2 == "20 de Febrero esq. Guemes"

    # Intersection and Avda.
    addr3 = clean_address(
        "avda. monseñor tavella y avda. ex - combatientes de malvina none"
    )
    assert "Av. Monseñor Tavella" in addr3
    assert "none" not in addr3

    # Empty address
    assert clean_address(None) == "S/N"
    assert clean_address("   ") == "S/N"


def test_clean_branch():
    # Strip bracketed address
    assert clean_branch("adrogue [esteban adrogué 1061]") == "Adrogué"
    assert clean_branch("campana [av. ingeniero a. rocca 222") == "Campana"

    # Strip sm prefix
    assert clean_branch("sm 140 orán - salta.") == "Orán - Salta"

    # Roman numerals title casing
    assert clean_branch("salta iii") == "Salta III"
    assert clean_branch("salta vii") == "Salta VII"


def test_resolve_geographic_info():
    # CABA / Federal Capital
    city, prov, code = resolve_geographic_info(
        city_raw="almagro",
        state_raw="CABA",
        branch_raw="diaz velez",
    )
    assert city == "Ciudad Autónoma de Buenos Aires"
    assert prov == "Ciudad Autónoma de Buenos Aires"
    assert code == "AR-C"

    # Cross-province rectification: Mendoza wrongly assigned to Buenos Aires
    city, prov, code = resolve_geographic_info(
        city_raw="mendoza",
        state_raw="Buenos Aires",
        branch_raw="mendoza",
    )
    assert city == "Mendoza"
    assert prov == "Mendoza"
    assert code == "AR-M"

    # Cross-province rectification: Resistencia wrongly assigned to Buenos Aires
    city, prov, code = resolve_geographic_info(
        city_raw="resistencia",
        state_raw="Buenos Aires",
        branch_raw="resistencia",
    )
    assert city == "Resistencia"
    assert prov == "Chaco"
    assert code == "AR-H"

    # Cross-province rectification: Libertad Salta wrongly assigned to Santa Fé
    city, prov, code = resolve_geographic_info(
        city_raw="capital",
        state_raw="Santa Fé",
        branch_raw="hipermercado salta",
        address_clean="Av. Monseñor Tavella",
    )
    assert city == "Salta"
    assert prov == "Salta"
    assert code == "AR-A"


def test_clean_point_of_sale_record():
    record = clean_point_of_sale_record(
        code="(11-2-1075)(changomas)",
        business="Wal Mart Argentina S.r.l",
        flag="Changomas",
        branch="salta ciudad judicial",
        address="avenida fuerza aerea esq. aguas blancas none",
        city="barrio castañares",
        state="Salta",
    )
    assert record.sepa_id == "11-2-1075"
    assert record.comercio_id == 11
    assert record.bandera_id == 2
    assert record.sucursal_id == 1075
    assert record.brand_name == "ChangoMás"
    assert record.store_format == "Supermercado"
    assert record.city == "Salta"
    assert record.province == "Salta"
    assert record.province_code == "AR-A"


def test_point_of_sale_orm_integration():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        cleaned = clean_point_of_sale_record(
            code="(10-3-695)(express)",
            business="Inc S.a",
            flag="Express",
            branch="almirante brown 261",
            address="almirante brown 261",
            city="caba",
            state="CABA",
        )
        pos = PointOfSale(
            code=cleaned.code,
            sepa_id=cleaned.sepa_id,
            comercio_id=cleaned.comercio_id,
            bandera_id=cleaned.bandera_id,
            sucursal_id=cleaned.sucursal_id,
            business_name=cleaned.business_name,
            holding_group=cleaned.holding_group,
            brand_name=cleaned.brand_name,
            store_format=cleaned.store_format,
            branch_name=cleaned.branch_name,
            address=cleaned.address,
            city=cleaned.city,
            province=cleaned.province,
            province_code=cleaned.province_code,
        )
        session.add(pos)
        session.commit()

        # Query back
        stmt = select(PointOfSale).where(PointOfSale.brand_name == "Carrefour Express")
        found = session.scalars(stmt).first()
        assert found is not None
        assert found.code == "(10-3-695)(express)"
        assert found.brand == "Carrefour Express"  # test backward compat property
        assert found.city == "Ciudad Autónoma de Buenos Aires"
        assert found.province_code == "AR-C"
