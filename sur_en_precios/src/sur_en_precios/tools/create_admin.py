"""CLI Tool to bootstrap the single administrator account for Sur en Precios."""

import argparse
import getpass
import sys
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sur_en_precios.adapters.database.repositories import SqlAlchemyUserRepository
from sur_en_precios.config import read_config
from sur_en_precios.domain.services import AuthService
from sur_en_precios.web.public_app.database import init_user_db


def create_admin_user(
    username: str,
    password: str,
    workdir_override: Optional[Path] = None,
) -> bool:
    """Creates the single admin user in user_data.sqlite."""
    config = read_config(workdir_override=workdir_override, should_create_override=True)
    user_db_path = config.get_user_db_path()

    val_user, err_user = AuthService.validate_username(username)
    if not val_user:
        print(f"Error de validación de usuario: {err_user}", file=sys.stderr)
        return False

    val_pass, err_pass = AuthService.validate_password(password)
    if not val_pass:
        print(f"Error de validación de contraseña: {err_pass}", file=sys.stderr)
        return False

    engine = create_engine(f"sqlite:///{user_db_path}")
    init_user_db(engine)

    with Session(engine) as session:
        user_repo = SqlAlchemyUserRepository(session)
        admin_count = user_repo.count_admins()
        if admin_count >= 1:
            print(
                "ERROR: Ya existe un usuario administrador registrado en el servidor.\n"
                "Por política de seguridad estricta, solo se permite un único administrador.",
                file=sys.stderr,
            )
            return False

        existing_user = user_repo.get_user_by_username(username)
        if existing_user:
            print(
                f"ERROR: Ya existe un usuario con el nombre '{username}'.",
                file=sys.stderr,
            )
            return False

        password_hash = AuthService.hash_password(password)
        admin = user_repo.create_user(
            username=username, password_hash=password_hash, is_admin=True
        )

    print("==================================================")
    print("   SUR EN PRECIOS — ADMINISTRADOR CONFIGURADO     ")
    print("==================================================")
    print(f" Usuario     : {admin.username}")
    print(" Rol         : Administrador Único")
    print(f" Base de Datos: {user_db_path}")
    print("==================================================")
    print(" El usuario administrador ha sido inicializado con éxito.\n")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inicializa el usuario administrador único para el servidor."
    )
    parser.add_argument("--username", "-u", help="Nombre de usuario del administrador")
    parser.add_argument(
        "--password", "-p", help="Contraseña segura para el administrador"
    )
    parser.add_argument(
        "--workdir", help="Directorio de trabajo (por defecto ~/Info/sur_en_precios)"
    )

    args = parser.parse_args()
    workdir_path = Path(args.workdir).resolve() if args.workdir else None

    username = args.username
    while not username:
        username = input("Ingrese el nombre de usuario del administrador: ").strip()

    password = args.password
    while not password:
        password = getpass.getpass("Ingrese la contraseña del administrador: ")
        confirm = getpass.getpass("Confirme la contraseña del administrador: ")
        if password != confirm:
            print("Las contraseñas no coinciden. Intente nuevamente.", file=sys.stderr)
            password = ""

    success = create_admin_user(
        username=username,
        password=password,
        workdir_override=workdir_path,
    )
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
