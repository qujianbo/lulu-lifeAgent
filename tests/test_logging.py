import json
import logging

from app.logging import AppLogger, configure_logging, shutdown_logging


def test_async_logging_splits_exact_levels_into_rotating_files(tmp_path) -> None:
    configure_logging("DEBUG", log_dir=str(tmp_path), max_bytes=4096, retention="2 days")
    logger = AppLogger.get("test.split")

    logger.debug("debug_event")
    logger.info("info_event", extra={"_item_id": 7})
    logger.warning("warning_event")
    logger.error("error_event")
    shutdown_logging()

    log_dir = tmp_path / "web"
    assert json.loads((log_dir / "debug.log").read_text())["record"]["message"] == "debug_event"
    info = json.loads((log_dir / "info.log").read_text())["record"]
    assert info["message"] == "info_event"
    assert info["extra"]["item_id"] == 7
    assert json.loads((log_dir / "warning.log").read_text())["record"]["message"] == "warning_event"
    assert json.loads((log_dir / "error.log").read_text())["record"]["message"] == "error_event"
    assert logging.getLogger().handlers
    configure_logging("INFO", log_dir=str(tmp_path / "restored"))
