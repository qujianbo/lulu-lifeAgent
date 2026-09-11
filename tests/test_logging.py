import json
import logging

from app.logging import AppLogger, configure_logging, shutdown_logging


def test_async_logging_splits_exact_levels_into_rotating_files(tmp_path) -> None:
    configure_logging("DEBUG", log_dir=str(tmp_path), max_bytes=4096, backup_count=2)
    logger = AppLogger.get("test.split")

    logger.debug("debug_event")
    logger.info("info_event", extra={"_item_id": 7})
    logger.warning("warning_event")
    logger.error("error_event")
    shutdown_logging()

    assert json.loads((tmp_path / "debug.log").read_text())["message"] == "debug_event"
    info = json.loads((tmp_path / "info.log").read_text())
    assert info["message"] == "info_event"
    assert info["item_id"] == 7
    assert json.loads((tmp_path / "warning.log").read_text())["message"] == "warning_event"
    assert json.loads((tmp_path / "error.log").read_text())["message"] == "error_event"
    assert logging.getLogger().handlers
    configure_logging("INFO", log_dir=str(tmp_path / "restored"))
