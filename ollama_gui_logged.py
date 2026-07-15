from __future__ import annotations

import argparse
import hashlib
import logging
import os
import platform
import queue
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import ollama_gui_chat as base

APP_TITLE = "Ollama Desktop Chat"
SETTINGS_DIR = Path.home() / ".ollama_desktop_chat"
LOG_DIR = SETTINGS_DIR / "logs"
DEFAULT_LOG_FILE = LOG_DIR / "ollama_gui_chat.log"
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 5
SESSION_ID = uuid.uuid4().hex[:12]
LOGGER = logging.getLogger("ollama_gui_chat")
LOG_CONTENT_ENABLED = False
ACTIVE_LOG_FILE = DEFAULT_LOG_FILE


class SessionContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.session_id = SESSION_ID
        return True


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on", "да"}


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GUI-чат для локальных моделей Ollama.")
    parser.add_argument(
        "--log-level",
        default=os.getenv("OLLAMA_CHAT_LOG_LEVEL", "INFO").upper(),
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
    )
    parser.add_argument(
        "--log-content",
        action="store_true",
        default=_env_flag("OLLAMA_CHAT_LOG_CONTENT"),
        help="Записывать полный текст запросов и ответов в DEBUG-журнал.",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=Path(os.getenv("OLLAMA_CHAT_LOG_FILE", DEFAULT_LOG_FILE)),
    )
    return parser.parse_args()


def configure_logging(
    *,
    level_name: str,
    include_content: bool,
    log_file: Path,
) -> Path:
    global LOG_CONTENT_ENABLED, ACTIVE_LOG_FILE

    LOG_CONTENT_ENABLED = include_content
    ACTIVE_LOG_FILE = log_file.expanduser().resolve()
    ACTIVE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, level_name.upper(), logging.INFO)

    for handler in list(LOGGER.handlers):
        handler.flush()
        handler.close()
    LOGGER.handlers.clear()
    LOGGER.setLevel(level)
    LOGGER.propagate = False

    formatter = logging.Formatter(
        fmt=(
            "%(asctime)s.%(msecs)03d | %(levelname)-8s | "
            "session=%(session_id)s | pid=%(process)d | "
            "thread=%(threadName)s | %(name)s | %(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    context_filter = SessionContextFilter()

    file_handler = RotatingFileHandler(
        ACTIVE_LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
        delay=False,
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(context_filter)
    LOGGER.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(context_filter)
    LOGGER.addHandler(console_handler)

    LOGGER.info(
        "Logging initialized level=%s file=%s rotation_bytes=%d backups=%d content=%s",
        level_name.upper(),
        ACTIVE_LOG_FILE,
        LOG_MAX_BYTES,
        LOG_BACKUP_COUNT,
        include_content,
    )
    if include_content:
        LOGGER.warning("Full prompt, answer, and thinking content logging is enabled")
    return ACTIVE_LOG_FILE


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:12]


def describe_text(text: str) -> str:
    return f"chars={len(text)} lines={text.count(chr(10)) + 1} sha256={_fingerprint(text)}"


def debug_text(label: str, text: str) -> None:
    if LOG_CONTENT_ENABLED:
        LOGGER.debug("%s content=%r", label, text)
    else:
        LOGGER.debug("%s %s", label, describe_text(text))


def safe_config(config: base.ModelConfig) -> dict[str, Any]:
    data = asdict(config)
    prompt = str(data.pop("system_prompt", ""))
    data["system_prompt"] = describe_text(prompt)
    return data


def install_exception_hooks() -> None:
    original_sys_hook = sys.excepthook

    def sys_hook(exc_type: type[BaseException], exc: BaseException, traceback: Any) -> None:
        LOGGER.critical("Uncaught main-thread exception", exc_info=(exc_type, exc, traceback))
        original_sys_hook(exc_type, exc, traceback)

    sys.excepthook = sys_hook

    if hasattr(threading, "excepthook"):
        original_thread_hook = threading.excepthook

        def thread_hook(args: threading.ExceptHookArgs) -> None:
            LOGGER.critical(
                "Uncaught worker exception thread=%s",
                args.thread.name if args.thread else "unknown",
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
            original_thread_hook(args)

        threading.excepthook = thread_hook


def open_log_directory() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if os.name == "nt":
            os.startfile(LOG_DIR)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(LOG_DIR)])
        else:
            subprocess.Popen(["xdg-open", str(LOG_DIR)])
        LOGGER.info("Opened log directory path=%s", LOG_DIR)
    except Exception:
        LOGGER.exception("Failed to open log directory path=%s", LOG_DIR)
        raise


class LoggingQueue(queue.Queue[tuple[str, Any]]):
    def put(
        self,
        item: tuple[str, Any],
        block: bool = True,
        timeout: float | None = None,
    ) -> None:
        event, payload = item
        if event in {"generation_error", "connection_error"}:
            LOGGER.error("UI event=%s payload=%s", event, payload)
        elif event == "done" and isinstance(payload, dict):
            LOGGER.info(
                "Generation event done id=%s stopped=%s stats=%s elapsed=%s",
                payload.get("generation_id"),
                payload.get("stopped"),
                payload.get("stats"),
                payload.get("elapsed"),
            )
        elif event in {"models", "connection_ok", "model_missing", "notice"}:
            LOGGER.debug("UI event=%s payload=%s", event, payload)
        super().put(item, block, timeout)


class LoggedOllamaChatApp(base.OllamaChatApp):
    def __init__(self, *, log_file: Path) -> None:
        self.log_file = log_file
        self.generation_id: str | None = None
        self.generation_started_at = 0.0
        LOGGER.info("Tk application initialization started")
        super().__init__()
        self.events = LoggingQueue()
        self._install_diagnostics_menu()
        LOGGER.info(
            "Tk application initialized model=%s host=%s",
            self.config_data.model,
            self.config_data.host,
        )

    def _install_diagnostics_menu(self) -> None:
        menu = base.tk.Menu(self)
        diagnostics = base.tk.Menu(menu, tearoff=False)
        diagnostics.add_command(label="Открыть журналы", command=self._open_logs)
        diagnostics.add_command(label="Показать путь к журналу", command=self._show_log_path)
        menu.add_cascade(label="Диагностика", menu=diagnostics)
        self.configure(menu=menu)

    def _open_logs(self) -> None:
        try:
            open_log_directory()
        except Exception as error:
            base.messagebox.showerror("Ошибка", str(error), parent=self)

    def _show_log_path(self) -> None:
        LOGGER.debug("Log path requested from GUI")
        base.messagebox.showinfo("Журнал", str(self.log_file), parent=self)

    def report_callback_exception(
        self,
        exc_type: type[BaseException],
        exc: BaseException,
        traceback: Any,
    ) -> None:
        LOGGER.exception("Tkinter callback exception", exc_info=(exc_type, exc, traceback))
        base.messagebox.showerror("Ошибка интерфейса", str(exc), parent=self)

    def refresh_models(self) -> None:
        LOGGER.info("Model list refresh requested host=%s", self.host_var.get().strip())
        super().refresh_models()

    def _models_worker(self, host: str) -> None:
        started = time.perf_counter()
        LOGGER.debug("Model list worker started host=%s", host)
        try:
            super()._models_worker(host)
        finally:
            LOGGER.debug(
                "Model list worker finished host=%s elapsed=%.3fs",
                host,
                time.perf_counter() - started,
            )

    def test_connection(self) -> None:
        LOGGER.info(
            "Connection test requested host=%s model=%s",
            self.host_var.get().strip(),
            self.model_var.get().strip(),
        )
        super().test_connection()

    def _test_connection_worker(self, host: str, model: str) -> None:
        started = time.perf_counter()
        LOGGER.debug("Connection worker started host=%s model=%s", host, model)
        try:
            super()._test_connection_worker(host, model)
        finally:
            LOGGER.debug(
                "Connection worker finished host=%s model=%s elapsed=%.3fs",
                host,
                model,
                time.perf_counter() - started,
            )

    def start_chat(self) -> None:
        LOGGER.info("Start chat requested")
        super().start_chat()
        if self.chat_started:
            LOGGER.info("New chat started config=%s", safe_config(self.config_data))

    def send_message(self) -> None:
        prompt = self.input_text.get("1.0", "end").strip()
        if prompt and not self.generation_active:
            self.generation_id = uuid.uuid4().hex[:12]
            self.generation_started_at = time.perf_counter()
            LOGGER.info(
                "Generation requested id=%s model=%s history_messages=%d options=%s",
                self.generation_id,
                self.config_data.model,
                len(self.messages),
                self.config_data.options(),
            )
            debug_text("user_prompt", prompt)
        super().send_message()

    def _chat_worker(self, message_snapshot: list[dict[str, str]]) -> None:
        LOGGER.debug(
            "Chat worker started id=%s thread=%s messages=%d keep_alive=%s think=%s",
            self.generation_id,
            threading.current_thread().name,
            len(message_snapshot),
            self.config_data.keep_alive,
            self.config_data.think,
        )
        try:
            super()._chat_worker(message_snapshot)
        finally:
            LOGGER.debug("Chat worker finished id=%s", self.generation_id)

    def _finish_generation(self, *, stopped: bool, stats: str) -> None:
        answer = "".join(self.current_answer_parts)
        thinking = "".join(self.current_thinking_parts)
        elapsed = time.perf_counter() - self.generation_started_at if self.generation_started_at else 0.0
        LOGGER.info(
            "Generation finished id=%s stopped=%s elapsed=%.3fs stats=%s answer=%s thinking=%s",
            self.generation_id,
            stopped,
            elapsed,
            stats,
            describe_text(answer),
            describe_text(thinking),
        )
        debug_text("assistant_answer", answer)
        if thinking:
            debug_text("model_thinking", thinking)
        super()._finish_generation(stopped=stopped, stats=stats)
        self.generation_id = None
        self.generation_started_at = 0.0

    def stop_generation(self) -> None:
        LOGGER.warning("Generation stop requested id=%s", self.generation_id)
        super().stop_generation()

    def new_chat(self) -> None:
        LOGGER.info("Context reset requested messages=%d", len(self.messages))
        super().new_chat()

    def export_chat(self) -> None:
        LOGGER.info("Chat export requested messages=%d", len(self.messages))
        super().export_chat()

    def _on_close(self) -> None:
        LOGGER.info(
            "Application close requested generation_active=%s id=%s messages=%d",
            self.generation_active,
            self.generation_id,
            len(self.messages),
        )
        super()._on_close()
        LOGGER.info("Tk application destroyed")


def main() -> None:
    args = parse_arguments()
    log_file = configure_logging(
        level_name=args.log_level,
        include_content=args.log_content,
        log_file=args.log_file,
    )
    install_exception_hooks()
    LOGGER.info(
        "Application startup app=%s python=%s executable=%s platform=%s cwd=%s",
        APP_TITLE,
        platform.python_version(),
        sys.executable,
        platform.platform(),
        Path.cwd(),
    )
    try:
        app = LoggedOllamaChatApp(log_file=log_file)
        app.mainloop()
    except Exception:
        LOGGER.critical("Fatal application error", exc_info=True)
        raise
    finally:
        LOGGER.info("Application process is exiting")
        for handler in LOGGER.handlers:
            handler.flush()


if __name__ == "__main__":
    main()
