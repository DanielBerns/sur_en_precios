"""Unit and integration tests for article search pagination."""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sur_en_precios.adapters.database.repositories import SqlAlchemyCatalogRepository
from sur_en_precios.domain.models_public import Article, PublicBase
from sur_en_precios.web.public_app import create_public_app
from sur_en_precios.web.public_app.schemas import Pagination


def test_pagination_helper_math():
    # Empty items
    p_empty = Pagination(page=1, per_page=20, total_items=0)
    assert p_empty.total_pages == 1
    assert p_empty.page == 1
    assert p_empty.start_item == 0
    assert p_empty.end_item == 0
    assert not p_empty.has_prev
    assert not p_empty.has_next

    # Single page results
    p_single = Pagination(page=1, per_page=20, total_items=12)
    assert p_single.total_pages == 1
    assert p_single.start_item == 1
    assert p_single.end_item == 12
    assert not p_single.has_prev
    assert not p_single.has_next
    assert list(p_single.iter_pages()) == [1]

    # Multiple pages (45 items -> 3 pages of 20)
    p_multi_1 = Pagination(page=1, per_page=20, total_items=45)
    assert p_multi_1.total_pages == 3
    assert p_multi_1.page == 1
    assert p_multi_1.start_item == 1
    assert p_multi_1.end_item == 20
    assert not p_multi_1.has_prev
    assert p_multi_1.has_next
    assert p_multi_1.next_num == 2
    assert list(p_multi_1.iter_pages()) == [1, 2, 3]

    p_multi_2 = Pagination(page=2, per_page=20, total_items=45)
    assert p_multi_2.page == 2
    assert p_multi_2.start_item == 21
    assert p_multi_2.end_item == 40
    assert p_multi_2.has_prev
    assert p_multi_2.prev_num == 1
    assert p_multi_2.has_next
    assert p_multi_2.next_num == 3

    p_multi_3 = Pagination(page=3, per_page=20, total_items=45)
    assert p_multi_3.page == 3
    assert p_multi_3.start_item == 41
    assert p_multi_3.end_item == 45
    assert p_multi_3.has_prev
    assert p_multi_3.prev_num == 2
    assert not p_multi_3.has_next

    # Out of bounds clamping
    p_clamp_high = Pagination(page=99, per_page=20, total_items=45)
    assert p_clamp_high.page == 3

    p_clamp_low = Pagination(page=-5, per_page=20, total_items=45)
    assert p_clamp_low.page == 1

    # Large page count with gaps
    p_large = Pagination(page=5, per_page=10, total_items=100)
    assert p_large.total_pages == 10
    pages = list(
        p_large.iter_pages(left_edge=1, left_current=1, right_current=1, right_edge=1)
    )
    assert 1 in pages
    assert 10 in pages
    assert None in pages  # Ellipsis gap


def test_repository_search_articles_paginated():
    engine = create_engine("sqlite:///:memory:")
    PublicBase.metadata.create_all(engine)

    with Session(engine) as session:
        # Create 45 articles matching "Fideos"
        articles = [
            Article(
                ean=f"7791000{i:03d}",
                name=f"Fideos Guiseros Paquete {i:02d} 500g",
                clean_description=f"Fideos Guiseros Paquete {i:02d} 500g",
                raw_description=f"FIDEOS GUISEROS {i:02d}",
                brand_name="Lucchetti" if i % 2 == 0 else "Matarazzo",
            )
            for i in range(1, 46)
        ]
        session.add_all(articles)
        session.commit()

        repo = SqlAlchemyCatalogRepository(session)

        # 1. Page 1 (20 items)
        page1_items, total = repo.search_articles_paginated(
            query="Fideos", page=1, per_page=20, mode="fuzzy"
        )
        assert total == 45
        assert len(page1_items) == 20

        # 2. Page 2 (20 items)
        page2_items, total2 = repo.search_articles_paginated(
            query="Fideos", page=2, per_page=20, mode="fuzzy"
        )
        assert total2 == 45
        assert len(page2_items) == 20

        # Verify no overlap between page 1 and page 2
        eans_p1 = {a.ean for a in page1_items}
        eans_p2 = {a.ean for a in page2_items}
        assert len(eans_p1.intersection(eans_p2)) == 0

        # 3. Page 3 (remaining 5 items)
        page3_items, total3 = repo.search_articles_paginated(
            query="Fideos", page=3, per_page=20, mode="fuzzy"
        )
        assert total3 == 45
        assert len(page3_items) == 5

        # 4. Exact mode search pagination
        exact_p1, exact_total = repo.search_articles_paginated(
            query="Fideos", page=1, per_page=15, mode="exact"
        )
        assert exact_total == 45
        assert len(exact_p1) == 15

        exact_p3, _ = repo.search_articles_paginated(
            query="Fideos", page=3, per_page=15, mode="exact"
        )
        assert len(exact_p3) == 15

        exact_p4, _ = repo.search_articles_paginated(
            query="Fideos", page=4, per_page=15, mode="exact"
        )
        assert len(exact_p4) == 0  # Beyond page count (45 / 15 = 3 pages)


def test_public_app_search_pagination_view(tmp_path: Path):
    workdir = tmp_path / "pagination_workdir"
    app = create_public_app(workdir=workdir)
    app.config["TESTING"] = True

    # Seed public DB with 35 articles
    config = app.config["APP_CONFIG"]
    public_engine = create_engine(f"sqlite:///{config.get_public_db_path()}")
    PublicBase.metadata.create_all(public_engine)

    with Session(public_engine) as session:
        articles = [
            Article(
                ean=f"7792000{i:03d}",
                name=f"Leche Entera Clasica {i:02d} 1L",
                clean_description=f"Leche Entera Clasica {i:02d} 1L",
                raw_description=f"LECHE ENTERA {i:02d}",
                brand_name="La Serenísima",
            )
            for i in range(1, 36)
        ]
        session.add_all(articles)
        session.commit()

    client = app.test_client()

    # 1. Search page 1 (default per_page=20)
    res_p1 = client.get("/?q=Leche")
    assert res_p1.status_code == 200
    html_p1 = res_p1.get_data(as_text=True)

    assert "Mostrando 1-20 de 35 artículos encontrados" in html_p1
    assert "Leche Entera Clasica 01 1L" in html_p1
    assert 'class="pagination"' in html_p1
    assert 'class="page-link active">1</span>' in html_p1
    assert "page=2" in html_p1

    # 2. Search page 2 (remaining 15 articles)
    res_p2 = client.get("/?q=Leche&page=2")
    assert res_p2.status_code == 200
    html_p2 = res_p2.get_data(as_text=True)

    assert "Mostrando 21-35 de 35 artículos encontrados" in html_p2
    assert 'class="page-link active">2</span>' in html_p2
    assert "page=1" in html_p2

    # 3. Non-matching search query displays empty state message
    res_empty = client.get("/?q=InexistenteTermXYZ999")
    assert res_empty.status_code == 200
    html_empty = res_empty.get_data(as_text=True)

    assert 'No se encontraron artículos para "InexistenteTermXYZ999"' in html_empty
    assert "Resultados de Búsqueda" not in html_empty
    assert 'class="pagination"' not in html_empty
