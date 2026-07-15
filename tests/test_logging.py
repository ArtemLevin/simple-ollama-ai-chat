from __future__ import annotations

import importlib
import logging
import sys
import tempfile
import types
import unittest
from logging.handlers import RotatingFileHandler
from pathlib import Path

if "ollama" not in sys.modules:
    module = types.ModuleType("ollama")

    class Client:  # pragma: no cover - test import stub
        pass

    class ResponseError(Exception):
        pass

    module.Client = Client
    module.ResponseError = ResponseError
    sys.modules["ollama"] = module

app = importlib.import_module("ollama_gui_logged")


class LoggingTests(unittest.TestCase):
    def tearDown(self) -> None:
        for handler in list(app.LOGGER.handlers):
            handler.flush()
            handler.close()
        app.LOGGER.handlers.clear()

    def test_debug_mode_redacts_message_content_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_file = Path(directory) / "app.log"
            app.configure_logging(level_name="DEBUG", include_content=False, log_file=log_file)
            secret = "секретный текст пользователя"
            app.debug_text("user_prompt", secret)
            for handler in app.LOGGER.handlers:
                handler.flush()
            content = log_file.read_text(encoding="utf-8")
            self.assertNotIn(secret, content)
            self.assertIn("sha256=", content)
            self.assertIn(f"chars={len(secret)}", content)

    def test_explicit_content_mode_writes_message_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_file = Path(directory) / "app.log"
            app.configure_logging(level_name="DEBUG", include_content=True, log_file=log_file)
            secret = "диагностический текст"
            app.debug_text("assistant_answer", secret)
            for handler in app.LOGGER.handlers:
                handler.flush()
            content = log_file.read_text(encoding="utf-8")
            self.assertIn(secret, content)
            self.assertIn("Full prompt, answer, and thinking content", content)

    def test_rotating_file_handler_has_expected_limits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_file = Path(directory) / "app.log"
            app.configure_logging(level_name="INFO", include_content=False, log_file=log_file)
            handlers = [
                handler for handler in app.LOGGER.handlers if isinstance(handler, RotatingFileHandler)
            ]
            self.assertEqual(len(handlers), 1)
            self.assertEqual(handlers[0].maxBytes, app.LOG_MAX_BYTES)
            self.assertEqual(handlers[0].backupCount, app.LOG_BACKUP_COUNT)

    def test_log_records_include_session_and_thread(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_file = Path(directory) / "app.log"
            app.configure_logging(level_name="INFO", include_content=False, log_file=log_file)
            app.LOGGER.info("test record")
            for handler in app.LOGGER.handlers:
                handler.flush()
            content = log_file.read_text(encoding="utf-8")
            self.assertIn("session=", content)
            self.assertIn("thread=MainThread", content)
            self.assertIn("test record", content)


if __name__ == "__main__":
    logging.raiseExceptions = True
    unittest.main()
