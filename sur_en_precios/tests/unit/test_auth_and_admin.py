"""Comprehensive test suite for Authentication, Admin capabilities, and Daily Updates."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sur_en_precios.adapters.database.repositories import SqlAlchemyUserRepository
from sur_en_precios.domain.services import AuthService
from sur_en_precios.tools.create_admin import create_admin_user
from sur_en_precios.web.public_app.app import create_public_app
from sur_en_precios.web.public_app.database import init_user_db


class TestAuthService:
    """Tests for AuthService domain validation and hashing rules."""

    def test_validate_username(self):
        # Valid usernames
        assert AuthService.validate_username("juan_perez")[0] is True
        assert AuthService.validate_username("maria.lopez")[0] is True
        assert AuthService.validate_username("usuario-123")[0] is True
        assert AuthService.validate_username("abc")[0] is True

        # Invalid usernames
        assert AuthService.validate_username("")[0] is False
        assert AuthService.validate_username("ab")[0] is False  # Too short
        assert AuthService.validate_username("a" * 35)[0] is False  # Too long
        assert AuthService.validate_username("123456")[0] is False  # Only digits
        assert (
            AuthService.validate_username("user@invalid")[0] is False
        )  # Invalid char @
        assert AuthService.validate_username("user name")[0] is False  # Space

    def test_validate_password(self):
        # Valid passwords (>= 10 chars, letters + digits/symbols, not blacklisted)
        assert AuthService.validate_password("Segura_2026!")[0] is True
        assert AuthService.validate_password("claveLarga123")[0] is True

        # Invalid passwords
        assert AuthService.validate_password("")[0] is False
        assert AuthService.validate_password("Corta_12")[0] is False  # < 10 chars
        assert (
            AuthService.validate_password("sololetrassinningunnumero")[0] is False
        )  # No digits
        assert AuthService.validate_password("123456789012")[0] is False  # Blacklisted
        assert AuthService.validate_password("password123")[0] is False  # Blacklisted

    def test_hash_and_verify_password(self):
        password = "MiSuperPassword123"
        hashed = AuthService.hash_password(password)
        assert hashed.startswith("$2b$12$")
        assert AuthService.verify_password(password, hashed) is True
        assert AuthService.verify_password("wrong_password", hashed) is False
        assert AuthService.verify_password("", hashed) is False

    def test_dummy_verify_timing(self):
        # Dummy verify should complete gracefully without throwing errors
        AuthService.dummy_verify()


class TestSingleAdminCreation:
    """Tests that only one single admin user can ever exist."""

    @pytest.fixture
    def user_repo(self):
        engine = create_engine("sqlite:///:memory:")
        init_user_db(engine)
        session = Session(engine)
        yield SqlAlchemyUserRepository(session)
        session.close()

    def test_single_admin_enforcement(self, user_repo: SqlAlchemyUserRepository):
        pwd_hash = AuthService.hash_password("admin_pass_2026")

        # First admin creation succeeds
        admin1 = user_repo.create_user("admin_principal", pwd_hash, is_admin=True)
        assert admin1.id is not None
        assert admin1.is_admin is True
        assert user_repo.count_admins() == 1

        # Second admin creation must be rejected
        with pytest.raises(
            ValueError, match="Solo se permite un único usuario administrador"
        ):
            user_repo.create_user("admin_segundo", pwd_hash, is_admin=True)

    def test_create_admin_cli_tool(self, tmp_path: Path):
        workdir = tmp_path / "cli_workdir"

        # First CLI creation -> True
        res1 = create_admin_user(
            username="super_admin",
            password="PasswordAdmin123!",
            workdir_override=workdir,
        )
        assert res1 is True

        # Second CLI creation attempt -> False
        res2 = create_admin_user(
            username="otro_admin",
            password="OtraPassword123!",
            workdir_override=workdir,
        )
        assert res2 is False


class TestAuthAndAdminWebEndpoints:
    """Integration tests for web authentication, session handling, and admin privileges."""

    @pytest.fixture
    def app_and_client(self, tmp_path: Path):
        workdir = tmp_path / "web_auth_workdir"
        app = create_public_app(workdir=workdir)
        app.config["TESTING"] = False  # Real auth enforcement mode
        client = app.test_client()
        return app, client, workdir

    def test_unauthenticated_baskets_redirects_to_login(self, app_and_client):
        _, client, _ = app_and_client
        res = client.get("/baskets", follow_redirects=False)
        assert res.status_code == 302
        assert "/auth/login" in res.headers["Location"]

    def test_registration_and_login_flow(self, app_and_client):
        app, client, _ = app_and_client

        # 1. Registration fails without disclaimer checkbox
        res_fail = client.post(
            "/auth/register",
            data={
                "username": "nuevo_usuario",
                "password": "PasswordSegura123!",
                "confirm_password": "PasswordSegura123!",
            },
            follow_redirects=True,
        )
        assert "Debe aceptar la condición" in res_fail.get_data(as_text=True)

        # 2. Registration succeeds with disclaimer
        res_reg = client.post(
            "/auth/register",
            data={
                "username": "nuevo_usuario",
                "password": "PasswordSegura123!",
                "confirm_password": "PasswordSegura123!",
                "disclaimer_ack": "1",
            },
            follow_redirects=True,
        )
        assert res_reg.status_code == 200
        assert "Cuenta creada exitosamente" in res_reg.get_data(as_text=True)

        # 3. Access baskets while authenticated
        res_baskets = client.get("/baskets")
        assert res_baskets.status_code == 200
        assert "Mis Canastas de Compras" in res_baskets.get_data(as_text=True)

        # 4. Logout
        res_logout = client.get("/auth/logout", follow_redirects=True)
        assert "Has cerrado sesión correctamente" in res_logout.get_data(as_text=True)

        # 5. Login with invalid password fails
        res_bad_login = client.post(
            "/auth/login",
            data={"username": "nuevo_usuario", "password": "wrongpassword"},
            follow_redirects=True,
        )
        assert "incorrectos" in res_bad_login.get_data(as_text=True)

        # 6. Login with correct credentials succeeds
        res_good_login = client.post(
            "/auth/login",
            data={"username": "nuevo_usuario", "password": "PasswordSegura123!"},
            follow_redirects=True,
        )
        assert "Bienvenido/a" in res_good_login.get_data(as_text=True)

    def test_regular_user_denied_admin_panel(self, app_and_client):
        _, client, _ = app_and_client

        # Register regular user
        client.post(
            "/auth/register",
            data={
                "username": "usuario_comun",
                "password": "PasswordSegura123!",
                "confirm_password": "PasswordSegura123!",
                "disclaimer_ack": "1",
            },
        )

        # Attempt to access admin routes -> denied
        res_admin = client.get("/admin", follow_redirects=True)
        assert "No tienes permisos de administrador" in res_admin.get_data(as_text=True)

        res_users = client.get("/admin/users", follow_redirects=True)
        assert "No tienes permisos de administrador" in res_users.get_data(as_text=True)

    def test_admin_capabilities_and_user_deletion(self, app_and_client):
        app, client, workdir = app_and_client

        # 1. Bootstrap single admin via tool
        create_admin_user(
            username="admin_boss",
            password="SuperAdminPassword123!",
            workdir_override=workdir,
        )

        # 2. Register a regular user who creates a basket
        client.post(
            "/auth/register",
            data={
                "username": "victima",
                "password": "PasswordSegura123!",
                "confirm_password": "PasswordSegura123!",
                "disclaimer_ack": "1",
            },
        )
        client.post(
            "/baskets/create", data={"name": "Canasta de Victima", "eans": "779001"}
        )

        # Logout regular user
        client.get("/auth/logout")

        # 3. Log in as admin
        res_admin_login = client.post(
            "/auth/login",
            data={"username": "admin_boss", "password": "SuperAdminPassword123!"},
            follow_redirects=True,
        )
        assert res_admin_login.status_code == 200

        # 4. Admin accesses dashboard
        res_dash = client.get("/admin/dashboard")
        assert res_dash.status_code == 200
        assert "Panel de Administración" in res_dash.get_data(as_text=True)

        # 5. Admin audits all baskets (including victim's private basket)
        res_all_b = client.get("/admin/baskets")
        assert res_all_b.status_code == 200
        assert "Canasta de Victima" in res_all_b.get_data(as_text=True)
        assert "victima" in res_all_b.get_data(as_text=True)

        # 6. Admin accesses users list
        res_users = client.get("/admin/users")
        assert "victima" in res_users.get_data(as_text=True)

        # 7. Admin deletes regular user
        with app.app_context():
            session_factory = app.extensions["user_session_factory"]
            with session_factory() as session:
                repo = SqlAlchemyUserRepository(session)
                v_user = repo.get_user_by_username("victima")
                assert v_user is not None
                v_id = v_user.id

        res_del = client.post(f"/admin/users/{v_id}/delete", follow_redirects=True)
        assert "fueron eliminados con éxito" in res_del.get_data(as_text=True)

        # Verify user and their basket were deleted
        with app.app_context():
            with session_factory() as session:
                repo = SqlAlchemyUserRepository(session)
                assert repo.get_user_by_username("victima") is None
                assert len(repo.get_all_baskets()) == 0

        # 8. Admin attempts to delete own account -> must be prevented
        with app.app_context():
            with session_factory() as session:
                repo = SqlAlchemyUserRepository(session)
                admin_obj = repo.get_user_by_username("admin_boss")
                admin_id = admin_obj.id

        res_del_self = client.post(
            f"/admin/users/{admin_id}/delete", follow_redirects=True
        )
        assert "No puedes eliminar tu propia cuenta" in res_del_self.get_data(
            as_text=True
        )

    def test_admin_system_diagnostics_endpoint(self, app_and_client):
        app, client, workdir = app_and_client

        # 1. Bootstrap single admin via tool
        create_admin_user(
            username="admin_sys",
            password="SuperAdminPassword123!",
            workdir_override=workdir,
        )

        # 2. Anonymous user cannot access /admin/system
        res_anon = client.get("/admin/system")
        assert res_anon.status_code == 302
        assert "/auth/login" in res_anon.headers["Location"]

        # 3. Log in as admin
        client.post(
            "/auth/login",
            data={"username": "admin_sys", "password": "SuperAdminPassword123!"},
            follow_redirects=True,
        )

        # 4. Admin accesses /admin/system
        res_system = client.get("/admin/system")
        assert res_system.status_code == 200
        html = res_system.get_data(as_text=True)

        # Assert presence of diagnostics and UNPSJB sync info
        assert "Estado del Catálogo y Sincronización" in html
        assert "Diagnóstico de Archivo (public.sqlite)" in html
        assert "Flujo de Sincronización UNPSJB" in html
        assert "Universidad Nacional de la Patagonia San Juan Bosco" in html

        # Assert absence of manual execution button and pythonanywhere cron
        assert "Ejecutar Actualización Ahora" not in html
        assert "Cron Diario" not in html
        assert "Tasks" not in html

        # 5. POST to /admin/system is forbidden (405 Method Not Allowed)
        res_post = client.post("/admin/system")
        assert res_post.status_code == 405
