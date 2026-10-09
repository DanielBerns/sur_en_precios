from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, Response, jsonify, render_template_string, request
from sqlalchemy import DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from sur_en_precios.config import read_config


class ControlBase(DeclarativeBase):
    pass


class ScraperLogModel(ControlBase):
    __tablename__ = "scraper_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


CONTROL_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sur en Precios — Panel de Control</title>
    <style>
        :root { --bg: #0f172a; --card: #1e293b; --accent: #38bdf8; --text: #f8fafc; --success: #22c55e; --danger: #ef4444; }
        body { font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 2rem; }
        .container { max-width: 1000px; margin: 0 auto; }
        h1 { color: var(--accent); margin-bottom: 0.5rem; }
        .card { background: var(--card); border-radius: 12px; padding: 1.5rem; margin-bottom: 2rem; border: 1px solid #334155; }
        table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
        th, td { text-align: left; padding: 0.75rem; border-bottom: 1px solid #334155; }
        th { color: var(--accent); }
        .badge { padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 0.85rem; }
        .badge-success { background: rgba(34, 197, 94, 0.2); color: var(--success); }
        .badge-danger { background: rgba(239, 68, 68, 0.2); color: var(--danger); }
    </style>
</head>
<body>
    <div class="container">
        <h1>Sur en Precios — Panel de Control</h1>
        <p>Monitoreo y comunicación de ejecuciones del recolector de datos.</p>
        
        <div class="card">
            <h2>Historial de Ejecuciones</h2>
            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Tarea</th>
                        <th>Estado</th>
                        <th>Tamaño (bytes)</th>
                        <th>Duración (ms)</th>
                        <th>Fecha</th>
                    </tr>
                </thead>
                <tbody>
                    {% for log in logs %}
                    <tr>
                        <td>#{{ log.id }}</td>
                        <td>{{ log.job_name }}</td>
                        <td>
                            {% if log.status == 'SUCCESS' %}
                                <span class="badge badge-success">EXITOSO</span>
                            {% else %}
                                <span class="badge badge-danger">ERROR</span>
                            {% endif %}
                        </td>
                        <td>{{ log.file_size_bytes }}</td>
                        <td>{{ log.duration_ms }} ms</td>
                        <td>{{ log.timestamp.strftime('%Y-%m-%d %H:%M:%S') }}</td>
                    </tr>
                    {% else %}
                    <tr><td colspan="6">No se encontraron registros de ejecución.</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
"""


def check_auth(username: str, password: str) -> bool:
    """Simple Basic Auth validator for few control users."""
    return username == "admin" and password == "sur_precios_2026"


def authenticate() -> Response:
    """Sends 401 response prompting for Basic Auth."""
    return Response(
        "Acceso denegado. Credenciales inválidas.",
        401,
        {"WWW-Authenticate": 'Basic realm="Sur en Precios Control"'},
    )


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)

    return decorated


def create_control_app(workdir: Path | None = None) -> Flask:
    """Factory creating Flask control application."""
    config = read_config(workdir_override=workdir, should_create_override=True)
    db_path = config.get_control_db_path()

    engine = create_engine(f"sqlite:///{db_path}")
    ControlBase.metadata.create_all(engine)

    app = Flask(__name__)

    @app.route("/")
    @requires_auth
    def dashboard():
        with Session(engine) as session:
            stmt = select(ScraperLogModel).order_by(ScraperLogModel.id.desc()).limit(50)
            logs = session.execute(stmt).scalars().all()
            return render_template_string(CONTROL_HTML_TEMPLATE, logs=logs)

    @app.route("/api/logs/scraper", methods=["POST"])
    def log_scraper_run():
        data = request.get_json() or {}
        with Session(engine) as session:
            log_entry = ScraperLogModel(
                job_name=data.get("job_name", "sepa_harvester"),
                status=data.get("status", "SUCCESS"),
                file_size_bytes=int(data.get("file_size_bytes", 0)),
                duration_ms=int(data.get("duration_ms", 0)),
                error_message=data.get("error_message"),
            )
            session.add(log_entry)
            session.commit()
        return jsonify({"status": "recorded"}), 201

    return app


if __name__ == "__main__":
    control_app = create_control_app()
    control_app.run(port=5001, debug=True)
