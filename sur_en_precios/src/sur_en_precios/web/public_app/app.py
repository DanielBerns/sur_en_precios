"""Backward-compatibility module forwarding to application.py."""

from sur_en_precios.web.public_app.application import (  # noqa: F401
    create_app,
    create_public_app,
    get_locale,
    main,
)

if __name__ == "__main__":
    main()
