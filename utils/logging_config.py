import logging


def configure_logging(level: int = logging.INFO) -> None:
    """Apply a concise logging format across the app."""
    logging.basicConfig(
        level=level,
        format="%(levelname).1s %(asctime)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
