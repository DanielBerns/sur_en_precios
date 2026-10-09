import logging
from logging.handlers import RotatingFileHandler

from pythonjsonlogger import jsonlogger

from sur_en_precios.config import Config


def setup_application_logging(config: Config) -> logging.Logger:
    """Configures structured JSON logging with RotatingFileHandler and ConsoleHandler."""
    logger = logging.getLogger("sur_en_precios")
    log_level_str = config.get_log_level().upper()
    logger.setLevel(getattr(logging, log_level_str, logging.INFO))

    # Avoid adding duplicate handlers if re-initialized
    if logger.handlers:
        return logger

    # JSON Formatter
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(module)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level"},
    )

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Rotating File Handler in log_dir
    log_file_path = config.log_dir / "sur_en_precios.log.json"
    file_handler = RotatingFileHandler(
        filename=log_file_path,
        maxBytes=config.settings.logging.max_bytes,
        backupCount=config.settings.logging.backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
