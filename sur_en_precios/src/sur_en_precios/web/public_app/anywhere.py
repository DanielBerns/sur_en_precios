"""PythonAnywhere WSGI entry point."""

try:
    from sur_en_precios.web.public_app.application import create_app
except ImportError:
    from application import create_app  # type: ignore[no-redef]

app = create_app()
application = app
