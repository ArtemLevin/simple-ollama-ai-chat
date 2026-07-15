from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from ollama import Client, ResponseError
except ImportError as exc:
    raise SystemExit(
        "Не установлен Python-клиент Ollama.\n"
        "В каталоге проекта выполните:\n"
        "    uv sync\n"
        "Затем запустите приложение командой:\n"
        "    uv run python ollama_gui_chat.py"
    ) from exc


APP_TITLE = "Ollama Desktop Chat"
DEFAULT_MODEL = "qwen3.5:9b"
DEFAULT_HOST = "http://localhost:11434"
SETTINGS_DIR = Path.home() / ".ollama_desktop_chat"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"

SYSTEM_PROMPTS = {
    "Универсальный ассистент": (
        "Ты полезный русскоязычный ассистент. Отвечай точно, "
        "структурированно и по существу. Явно отмечай допущения."
    ),
    "Программист": (
        "Ты опытный senior-разработчик. Предлагай практичные, безопасные "
        "и поддерживаемые решения. Для кода учитывай обработку ошибок, "
        "типизацию, тестируемость и особенности среды пользователя."
    ),
    "Преподаватель": (
        "Ты опытный преподаватель. Объясняй материал последовательно, "
        "от базовой идеи к применению. Используй понятные примеры, "
        "проверяй логические переходы и выделяй типичные ошибки."
    ),
    "Редактор": (
        "Ты профессиональный редактор. Сохраняй исходный смысл, улучшай "
        "ясность, композицию, точность формулировок и естественность языка."
    ),
    "Свой промпт": "",
}

GENERATION_PRESETS: dict[str, dict[str, Any]] = {
    "Сбалансированный": {
        "temperature": 0.7,
        "top_p": 0.9,
        "top_k": 40,
        "min_p": 0.0,
        "repeat_penalty": 1.1,
        "repeat_last_n": 64,
    },
    "Точный": {
        "temperature": 0.2,
        "top_p": 0.75,
        "top_k": 20,
        "min_p": 0.05,
        "repeat_penalty": 1.1,
        "repeat_last_n": 64,
    },
    "Творческий": {
        "temperature": 1.0,
        "top_p": 0.95,
        "top_k": 80,
        "min_p": 0.0,
        "repeat_penalty": 1.05,
        "repeat_last_n": 64,
    },
    "Код": {
        "temperature": 0.15,
        "top_p": 0.8,
        "top_k": 30,
        "min_p": 0.05,
        "repeat_penalty": 1.05,
        "repeat_last_n": 128,
    },
    "Пользовательский": {},
}

THINK_LABEL_TO_VALUE: dict[str, bool | str | None] = {
    "Отключено": None,
    "Включено": True,
    "Низкая глубина": "low",
    "Средняя глубина": "medium",
    "Высокая глубина": "high",
}
THINK_VALUE_TO_LABEL = {
    None: "Отключено",
    False: "Отключено",
    True: "Включено",
    "low": "Низкая глубина",
    "medium": "Средняя глубина",
    "high": "Высокая глубина",
}


@dataclass(slots=True)
class ModelConfig:
    host: str = DEFAULT_HOST
    model: str = DEFAULT_MODEL
    system_prompt: str = SYSTEM_PROMPTS["Универсальный ассистент"]
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 40
    min_p: float = 0.0
    repeat_penalty: float = 1.1
    repeat_last_n: int = 64
    num_ctx: int = 8192
    num_predict: int = 2048
    seed: int = 0
    keep_alive: str = "5m"
    think: bool | str | None = None
    show_thinking: bool = False

    @classmethod
    def load(cls) -> "ModelConfig":
        if not SETTINGS_FILE.exists():
            return cls()

        try:
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            allowed = {item.name for item in fields(cls)}
            clean = {key: value for key, value in raw.items() if key in allowed}
            return cls(**clean)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return cls()

    def save(self) -> None:
        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def options(self) -> dict[str, int | float]:
        return {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "min_p": self.min_p,
            "repeat_penalty": self.repeat_penalty,
            "repeat_last_n": self.repeat_last_n,
            "num_ctx": self.num_ctx,
            "num_predict": self.num_predict,
            "seed": self.seed,
        }


class ScrollableFrame(ttk.Frame):
    """Прокручиваемый контейнер для длинного экрана настроек."""

    def __init__(self, master: tk.Misc, **kwargs: Any) -> None:
        super().__init__(master, **kwargs)

        self.canvas = tk.Canvas(
            self,
            highlightthickness=0,
            borderwidth=0,
            background="#f4f6f8",
        )
        self.scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
        )
        self.content = ttk.Frame(self.canvas, padding=(28, 20, 28, 28))
        self.window_id = self.canvas.create_window(
            (0, 0),
            window=self.content,
            anchor="nw",
        )

        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.content.bind("<Configure>", self._sync_scroll_region)
        self.canvas.bind("<Configure>", self._sync_width)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _sync_scroll_region(self, _event: tk.Event[Any]) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _sync_width(self, event: tk.Event[Any]) -> None:
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def _on_mousewheel(self, event: tk.Event[Any]) -> None:
        if self.winfo_ismapped():
            self.canvas.yview_scroll(int(-event.delta / 120), "units")


class OllamaChatApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()

        self.title(APP_TITLE)
        self.geometry("1180x820")
        self.minsize(960, 680)
        self.configure(background="#f4f6f8")

        self.config_data = ModelConfig.load()
        self.client: Client | None = None
        self.messages: list[dict[str, str]] = []
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.stop_event = threading.Event()
        self.generation_active = False
        self.current_answer_parts: list[str] = []
        self.current_thinking_parts: list[str] = []
        self.answer_header_visible = False
        self.thinking_header_visible = False
        self.chat_started = False

        self._configure_styles()
        self._build_settings_view()
        self._build_chat_view()
        self._show_settings()

        self.after(80, self._process_events)
        self.after(250, self.refresh_models)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # Общая настройка интерфейса
    # ------------------------------------------------------------------

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", font=("Segoe UI", 10))
        style.configure("TFrame", background="#f4f6f8")
        style.configure("Card.TFrame", background="#ffffff")
        style.configure(
            "Title.TLabel",
            background="#f4f6f8",
            foreground="#172033",
            font=("Segoe UI Semibold", 24),
        )
        style.configure(
            "Subtitle.TLabel",
            background="#f4f6f8",
            foreground="#667085",
            font=("Segoe UI", 10),
        )
        style.configure(
            "CardTitle.TLabel",
            background="#ffffff",
            foreground="#172033",
            font=("Segoe UI Semibold", 13),
        )
        style.configure(
            "CardText.TLabel",
            background="#ffffff",
            foreground="#667085",
        )
        style.configure(
            "Primary.TButton",
            font=("Segoe UI Semibold", 10),
            padding=(16, 10),
        )
        style.configure(
            "Secondary.TButton",
            padding=(14, 9),
        )
        style.configure(
            "Status.TLabel",
            background="#ffffff",
            foreground="#475467",
        )
        style.configure(
            "ChatHeader.TFrame",
            background="#ffffff",
        )
        style.configure(
            "ChatTitle.TLabel",
            background="#ffffff",
            foreground="#172033",
            font=("Segoe UI Semibold", 14),
        )
        style.configure(
            "ChatMeta.TLabel",
            background="#ffffff",
            foreground="#667085",
        )

    @staticmethod
    def _card(parent: tk.Misc) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Card.TFrame", padding=20)
        return frame

    @staticmethod
    def _labeled_entry(
        parent: tk.Misc,
        row: int,
        label: str,
        variable: tk.StringVar,
        *,
        width: int = 18,
        hint: str | None = None,
    ) -> ttk.Entry:
        ttk.Label(parent, text=label, style="CardText.TLabel").grid(
            row=row,
            column=0,
            sticky="w",
            padx=(0, 12),
            pady=(7, 2),
        )
        entry = ttk.Entry(parent, textvariable=variable, width=width)
        entry.grid(row=row, column=1, sticky="ew", pady=(7, 2))
        if hint:
            ttk.Label(parent, text=hint, style="CardText.TLabel").grid(
                row=row + 1,
                column=1,
                sticky="w",
                pady=(0, 5),
            )
        return entry

    # ------------------------------------------------------------------
    # Экран настройки модели
    # ------------------------------------------------------------------

    def _build_settings_view(self) -> None:
        self.settings_view = ScrollableFrame(self)
        body = self.settings_view.content
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        heading = ttk.Frame(body)
        heading.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 18))
        heading.columnconfigure(0, weight=1)

        ttk.Label(
            heading,
            text="Настройка локальной модели",
            style="Title.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            heading,
            text=(
                "Проверьте подключение, выберите модель и задайте параметры "
                "генерации перед началом диалога."
            ),
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(5, 0))

        # Подключение ---------------------------------------------------
        connection = self._card(body)
        connection.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(0, 14),
        )
        connection.columnconfigure(1, weight=1)

        ttk.Label(
            connection,
            text="1. Подключение к Ollama",
            style="CardTitle.TLabel",
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 12))

        self.host_var = tk.StringVar(value=self.config_data.host)
        self.model_var = tk.StringVar(value=self.config_data.model)
        self.connection_status_var = tk.StringVar(
            value="Проверка подключения ещё не выполнялась."
        )

        ttk.Label(
            connection,
            text="Адрес API",
            style="CardText.TLabel",
        ).grid(row=1, column=0, sticky="w", padx=(0, 12))
        ttk.Entry(connection, textvariable=self.host_var).grid(
            row=1,
            column=1,
            sticky="ew",
            padx=(0, 12),
        )
        ttk.Button(
            connection,
            text="Обновить модели",
            style="Secondary.TButton",
            command=self.refresh_models,
        ).grid(row=1, column=2, sticky="ew")

        ttk.Label(
            connection,
            text="Модель",
            style="CardText.TLabel",
        ).grid(row=2, column=0, sticky="w", padx=(0, 12), pady=(12, 0))
        self.model_combo = ttk.Combobox(
            connection,
            textvariable=self.model_var,
            state="normal",
        )
        self.model_combo.grid(
            row=2,
            column=1,
            sticky="ew",
            padx=(0, 12),
            pady=(12, 0),
        )
        ttk.Button(
            connection,
            text="Проверить",
            style="Secondary.TButton",
            command=self.test_connection,
        ).grid(row=2, column=2, sticky="ew", pady=(12, 0))

        self.connection_status_label = ttk.Label(
            connection,
            textvariable=self.connection_status_var,
            style="Status.TLabel",
        )
        self.connection_status_label.grid(
            row=3,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(12, 0),
        )

        # Поведение -----------------------------------------------------
        behavior = self._card(body)
        behavior.grid(row=2, column=0, sticky="nsew", padx=(0, 7), pady=(0, 14))
        behavior.columnconfigure(0, weight=1)

        ttk.Label(
            behavior,
            text="2. Роль и поведение",
            style="CardTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(
            behavior,
            text="Шаблон системного промпта",
            style="CardText.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(14, 4))

        self.prompt_preset_var = tk.StringVar(value="Свой промпт")
        self.prompt_combo = ttk.Combobox(
            behavior,
            textvariable=self.prompt_preset_var,
            values=list(SYSTEM_PROMPTS),
            state="readonly",
        )
        self.prompt_combo.grid(row=2, column=0, sticky="ew")
        self.prompt_combo.bind("<<ComboboxSelected>>", self._apply_prompt_preset)

        ttk.Label(
            behavior,
            text="Системный промпт",
            style="CardText.TLabel",
        ).grid(row=3, column=0, sticky="w", pady=(14, 4))

        self.system_text = tk.Text(
            behavior,
            height=12,
            wrap="word",
            relief="solid",
            borderwidth=1,
            font=("Segoe UI", 10),
            padx=10,
            pady=9,
            undo=True,
        )
        self.system_text.grid(row=4, column=0, sticky="nsew")
        self.system_text.insert("1.0", self.config_data.system_prompt)

        # Sampling ------------------------------------------------------
        sampling = self._card(body)
        sampling.grid(row=2, column=1, sticky="nsew", padx=(7, 0), pady=(0, 14))
        sampling.columnconfigure(1, weight=1)

        ttk.Label(
            sampling,
            text="3. Sampling и повторения",
            style="CardTitle.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        self.generation_preset_var = tk.StringVar(value="Сбалансированный")
        ttk.Label(
            sampling,
            text="Профиль",
            style="CardText.TLabel",
        ).grid(row=1, column=0, sticky="w", padx=(0, 12), pady=(14, 4))
        preset_combo = ttk.Combobox(
            sampling,
            textvariable=self.generation_preset_var,
            values=list(GENERATION_PRESETS),
            state="readonly",
        )
        preset_combo.grid(row=1, column=1, sticky="ew", pady=(14, 4))
        preset_combo.bind("<<ComboboxSelected>>", self._apply_generation_preset)

        self.temperature_var = tk.StringVar(value=str(self.config_data.temperature))
        self.top_p_var = tk.StringVar(value=str(self.config_data.top_p))
        self.top_k_var = tk.StringVar(value=str(self.config_data.top_k))
        self.min_p_var = tk.StringVar(value=str(self.config_data.min_p))
        self.repeat_penalty_var = tk.StringVar(
            value=str(self.config_data.repeat_penalty)
        )
        self.repeat_last_n_var = tk.StringVar(
            value=str(self.config_data.repeat_last_n)
        )

        labels = [
            ("temperature", "Температура", self.temperature_var, "0.0–2.0"),
            ("top_p", "Top P", self.top_p_var, "0.0–1.0"),
            ("top_k", "Top K", self.top_k_var, "целое ≥ 0"),
            ("min_p", "Min P", self.min_p_var, "0.0–1.0"),
            (
                "repeat_penalty",
                "Штраф повторов",
                self.repeat_penalty_var,
                "обычно 1.0–1.5",
            ),
            (
                "repeat_last_n",
                "Окно повторов",
                self.repeat_last_n_var,
                "-1, 0 или целое",
            ),
        ]
        self.parameter_hints: list[ttk.Label] = []
        row = 2
        for _key, label, variable, hint in labels:
            ttk.Label(
                sampling,
                text=label,
                style="CardText.TLabel",
            ).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=(8, 2))
            ttk.Entry(sampling, textvariable=variable).grid(
                row=row,
                column=1,
                sticky="ew",
                pady=(8, 2),
            )
            hint_label = ttk.Label(
                sampling,
                text=hint,
                style="CardText.TLabel",
            )
            hint_label.grid(row=row + 1, column=1, sticky="w")
            self.parameter_hints.append(hint_label)
            row += 2

        # Контекст ------------------------------------------------------
        runtime = self._card(body)
        runtime.grid(row=3, column=0, sticky="nsew", padx=(0, 7), pady=(0, 14))
        runtime.columnconfigure(1, weight=1)

        ttk.Label(
            runtime,
            text="4. Контекст и выполнение",
            style="CardTitle.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        self.num_ctx_var = tk.StringVar(value=str(self.config_data.num_ctx))
        self.num_predict_var = tk.StringVar(value=str(self.config_data.num_predict))
        self.seed_var = tk.StringVar(value=str(self.config_data.seed))
        self.keep_alive_var = tk.StringVar(value=self.config_data.keep_alive)

        row = 1
        for label, variable, hint in (
            ("Контекст, токенов", self.num_ctx_var, "например 8192 или 32768"),
            ("Макс. ответ, токенов", self.num_predict_var, "-1 = без лимита"),
            ("Seed", self.seed_var, "0 = случайное поведение"),
            ("Keep alive", self.keep_alive_var, "например 5m, 1h или 0"),
        ):
            ttk.Label(
                runtime,
                text=label,
                style="CardText.TLabel",
            ).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=(10, 2))
            ttk.Entry(runtime, textvariable=variable).grid(
                row=row,
                column=1,
                sticky="ew",
                pady=(10, 2),
            )
            ttk.Label(
                runtime,
                text=hint,
                style="CardText.TLabel",
            ).grid(row=row + 1, column=1, sticky="w")
            row += 2

        # Рассуждение ---------------------------------------------------
        thinking = self._card(body)
        thinking.grid(row=3, column=1, sticky="nsew", padx=(7, 0), pady=(0, 14))
        thinking.columnconfigure(0, weight=1)

        ttk.Label(
            thinking,
            text="5. Режим рассуждения",
            style="CardTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(
            thinking,
            text=(
                "Доступность и поддерживаемые уровни зависят от выбранной "
                "модели и версии Ollama."
            ),
            style="CardText.TLabel",
            wraplength=420,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(8, 12))

        self.think_var = tk.StringVar(
            value=THINK_VALUE_TO_LABEL.get(
                self.config_data.think,
                "Отключено",
            )
        )
        ttk.Combobox(
            thinking,
            textvariable=self.think_var,
            values=list(THINK_LABEL_TO_VALUE),
            state="readonly",
        ).grid(row=2, column=0, sticky="ew")

        self.show_thinking_var = tk.BooleanVar(
            value=self.config_data.show_thinking
        )
        ttk.Checkbutton(
            thinking,
            text="Показывать текст рассуждения в чате",
            variable=self.show_thinking_var,
        ).grid(row=3, column=0, sticky="w", pady=(14, 0))

        # Нижняя панель -------------------------------------------------
        footer = ttk.Frame(body)
        footer.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        footer.columnconfigure(0, weight=1)

        self.return_chat_button = ttk.Button(
            footer,
            text="Вернуться в текущий чат",
            style="Secondary.TButton",
            command=self._show_chat,
        )
        self.return_chat_button.grid(row=0, column=1, padx=(0, 10))
        self.return_chat_button.grid_remove()

        ttk.Button(
            footer,
            text="Применить и начать новый чат",
            style="Primary.TButton",
            command=self.start_chat,
        ).grid(row=0, column=2)

    def _apply_prompt_preset(self, _event: tk.Event[Any] | None = None) -> None:
        name = self.prompt_preset_var.get()
        if name == "Свой промпт":
            return
        self.system_text.delete("1.0", "end")
        self.system_text.insert("1.0", SYSTEM_PROMPTS[name])

    def _apply_generation_preset(
        self,
        _event: tk.Event[Any] | None = None,
    ) -> None:
        preset = GENERATION_PRESETS.get(self.generation_preset_var.get(), {})
        mapping = {
            "temperature": self.temperature_var,
            "top_p": self.top_p_var,
            "top_k": self.top_k_var,
            "min_p": self.min_p_var,
            "repeat_penalty": self.repeat_penalty_var,
            "repeat_last_n": self.repeat_last_n_var,
        }
        for key, value in preset.items():
            mapping[key].set(str(value))

    def _mark_custom_preset(self) -> None:
        self.generation_preset_var.set("Пользовательский")

    def _read_settings(self) -> ModelConfig:
        def parse_float(
            variable: tk.StringVar,
            label: str,
            minimum: float | None = None,
            maximum: float | None = None,
        ) -> float:
            raw = variable.get().strip().replace(",", ".")
            try:
                value = float(raw)
            except ValueError as error:
                raise ValueError(f"«{label}» должно быть числом.") from error
            if minimum is not None and value < minimum:
                raise ValueError(f"«{label}» должно быть не меньше {minimum}.")
            if maximum is not None and value > maximum:
                raise ValueError(f"«{label}» должно быть не больше {maximum}.")
            return value

        def parse_int(
            variable: tk.StringVar,
            label: str,
            minimum: int | None = None,
            *,
            allowed: set[int] | None = None,
        ) -> int:
            raw = variable.get().strip()
            try:
                value = int(raw)
            except ValueError as error:
                raise ValueError(f"«{label}» должно быть целым числом.") from error
            if allowed and value in allowed:
                return value
            if minimum is not None and value < minimum:
                allowed_text = ""
                if allowed:
                    allowed_text = (
                        " или одним из значений "
                        + ", ".join(map(str, sorted(allowed)))
                    )
                raise ValueError(
                    f"«{label}» должно быть не меньше {minimum}{allowed_text}."
                )
            return value

        host = self.host_var.get().strip().rstrip("/")
        model = self.model_var.get().strip()
        system_prompt = self.system_text.get("1.0", "end").strip()

        if not host:
            raise ValueError("Укажите адрес Ollama API.")
        if not model:
            raise ValueError("Укажите имя модели.")
        if not system_prompt:
            raise ValueError("Системный промпт не должен быть пустым.")

        return ModelConfig(
            host=host,
            model=model,
            system_prompt=system_prompt,
            temperature=parse_float(
                self.temperature_var,
                "Температура",
                0.0,
                2.0,
            ),
            top_p=parse_float(self.top_p_var, "Top P", 0.0, 1.0),
            top_k=parse_int(self.top_k_var, "Top K", 0),
            min_p=parse_float(self.min_p_var, "Min P", 0.0, 1.0),
            repeat_penalty=parse_float(
                self.repeat_penalty_var,
                "Штраф повторов",
                0.0,
            ),
            repeat_last_n=parse_int(
                self.repeat_last_n_var,
                "Окно повторов",
                0,
                allowed={-1},
            ),
            num_ctx=parse_int(self.num_ctx_var, "Контекст", 256),
            num_predict=parse_int(
                self.num_predict_var,
                "Максимальный ответ",
                1,
                allowed={-1},
            ),
            seed=parse_int(self.seed_var, "Seed", 0),
            keep_alive=self.keep_alive_var.get().strip() or "5m",
            think=THINK_LABEL_TO_VALUE[self.think_var.get()],
            show_thinking=self.show_thinking_var.get(),
        )

    def refresh_models(self) -> None:
        host = self.host_var.get().strip().rstrip("/")
        if not host:
            self.connection_status_var.set("Сначала укажите адрес Ollama API.")
            return

        self.connection_status_var.set("Получение списка локальных моделей…")
        threading.Thread(
            target=self._models_worker,
            args=(host,),
            daemon=True,
        ).start()

    def _models_worker(self, host: str) -> None:
        try:
            client = Client(host=host)
            response = client.list()
            models = self._extract_model_names(response)
            self.events.put(("models", (host, models)))
        except Exception as error:
            self.events.put(("connection_error", str(error)))

    @staticmethod
    def _extract_model_names(response: Any) -> list[str]:
        raw_models = getattr(response, "models", None)
        if raw_models is None and isinstance(response, dict):
            raw_models = response.get("models", [])

        names: list[str] = []
        for item in raw_models or []:
            if isinstance(item, dict):
                name = item.get("model") or item.get("name")
            else:
                name = getattr(item, "model", None) or getattr(item, "name", None)
            if name:
                names.append(str(name))
        return sorted(set(names), key=str.casefold)

    def test_connection(self) -> None:
        host = self.host_var.get().strip().rstrip("/")
        model = self.model_var.get().strip()
        if not host or not model:
            messagebox.showwarning(
                "Недостаточно данных",
                "Укажите адрес API и имя модели.",
                parent=self,
            )
            return

        self.connection_status_var.set("Проверка сервера и выбранной модели…")
        threading.Thread(
            target=self._test_connection_worker,
            args=(host, model),
            daemon=True,
        ).start()

    def _test_connection_worker(self, host: str, model: str) -> None:
        try:
            client = Client(host=host)
            response = client.list()
            models = self._extract_model_names(response)
            if model not in models:
                self.events.put(("model_missing", (model, models)))
                return

            details = client.show(model)
            parameter_size = ""
            quantization = ""
            detail_obj = getattr(details, "details", None)
            if detail_obj is not None:
                parameter_size = str(
                    getattr(detail_obj, "parameter_size", "") or ""
                )
                quantization = str(
                    getattr(detail_obj, "quantization_level", "") or ""
                )
            suffix = " · ".join(
                item for item in (parameter_size, quantization) if item
            )
            self.events.put(("connection_ok", (model, suffix)))
        except Exception as error:
            self.events.put(("connection_error", str(error)))

    def start_chat(self) -> None:
        try:
            config = self._read_settings()
        except ValueError as error:
            messagebox.showerror("Проверьте настройки", str(error), parent=self)
            return

        self.config_data = config
        try:
            self.config_data.save()
        except OSError as error:
            messagebox.showwarning(
                "Настройки не сохранены",
                f"Не удалось записать файл настроек:\n{error}",
                parent=self,
            )

        self.client = Client(host=config.host)
        self.messages = [
            {
                "role": "system",
                "content": config.system_prompt,
            }
        ]
        self.chat_started = True
        self._clear_chat_widget()
        self._append_system_notice(
            f"Новый диалог: {config.model}. "
            f"Контекст: {config.num_ctx} токенов."
        )
        self._update_chat_header()
        self.return_chat_button.grid()
        self._show_chat()
        self.input_text.focus_set()

    # ------------------------------------------------------------------
    # Экран чата
    # ------------------------------------------------------------------

    def _build_chat_view(self) -> None:
        self.chat_view = ttk.Frame(self)
        self.chat_view.rowconfigure(1, weight=1)
        self.chat_view.columnconfigure(0, weight=1)

        header = ttk.Frame(
            self.chat_view,
            style="ChatHeader.TFrame",
            padding=(20, 14),
        )
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        ttk.Button(
            header,
            text="← Настройки",
            style="Secondary.TButton",
            command=self._show_settings,
        ).grid(row=0, column=0, rowspan=2, padx=(0, 16))

        self.chat_title_var = tk.StringVar(value=DEFAULT_MODEL)
        self.chat_meta_var = tk.StringVar(value=DEFAULT_HOST)

        ttk.Label(
            header,
            textvariable=self.chat_title_var,
            style="ChatTitle.TLabel",
        ).grid(row=0, column=1, sticky="w")
        ttk.Label(
            header,
            textvariable=self.chat_meta_var,
            style="ChatMeta.TLabel",
        ).grid(row=1, column=1, sticky="w", pady=(2, 0))

        ttk.Button(
            header,
            text="Экспорт",
            style="Secondary.TButton",
            command=self.export_chat,
        ).grid(row=0, column=2, rowspan=2, padx=(8, 0))
        ttk.Button(
            header,
            text="Новый чат",
            style="Secondary.TButton",
            command=self.new_chat,
        ).grid(row=0, column=3, rowspan=2, padx=(8, 0))

        transcript_frame = ttk.Frame(
            self.chat_view,
            style="Card.TFrame",
            padding=(18, 14),
        )
        transcript_frame.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=18,
            pady=(16, 10),
        )
        transcript_frame.rowconfigure(0, weight=1)
        transcript_frame.columnconfigure(0, weight=1)

        self.chat_text = tk.Text(
            transcript_frame,
            wrap="word",
            state="disabled",
            relief="flat",
            borderwidth=0,
            background="#ffffff",
            foreground="#1d2939",
            insertbackground="#1d2939",
            font=("Segoe UI", 11),
            padx=12,
            pady=12,
            spacing1=2,
            spacing3=6,
        )
        chat_scroll = ttk.Scrollbar(
            transcript_frame,
            orient="vertical",
            command=self.chat_text.yview,
        )
        self.chat_text.configure(yscrollcommand=chat_scroll.set)
        self.chat_text.grid(row=0, column=0, sticky="nsew")
        chat_scroll.grid(row=0, column=1, sticky="ns")

        self.chat_text.tag_configure(
            "user_header",
            font=("Segoe UI Semibold", 10),
            foreground="#175cd3",
            spacing1=12,
        )
        self.chat_text.tag_configure(
            "assistant_header",
            font=("Segoe UI Semibold", 10),
            foreground="#067647",
            spacing1=12,
        )
        self.chat_text.tag_configure(
            "thinking_header",
            font=("Segoe UI Semibold", 9),
            foreground="#7f56d9",
            spacing1=10,
        )
        self.chat_text.tag_configure(
            "thinking",
            font=("Segoe UI", 9, "italic"),
            foreground="#667085",
            lmargin1=14,
            lmargin2=14,
        )
        self.chat_text.tag_configure(
            "system",
            font=("Segoe UI", 9),
            foreground="#667085",
            justify="center",
            spacing1=8,
            spacing3=8,
        )
        self.chat_text.tag_configure(
            "body",
            font=("Segoe UI", 11),
            foreground="#1d2939",
            lmargin1=4,
            lmargin2=4,
        )

        composer = ttk.Frame(
            self.chat_view,
            style="Card.TFrame",
            padding=(16, 12),
        )
        composer.grid(
            row=2,
            column=0,
            sticky="ew",
            padx=18,
            pady=(0, 16),
        )
        composer.columnconfigure(0, weight=1)

        self.input_text = tk.Text(
            composer,
            height=4,
            wrap="word",
            relief="solid",
            borderwidth=1,
            font=("Segoe UI", 11),
            padx=10,
            pady=9,
            undo=True,
        )
        self.input_text.grid(row=0, column=0, rowspan=2, sticky="ew")
        self.input_text.bind("<Return>", self._on_enter)
        self.input_text.bind("<Shift-Return>", self._on_shift_enter)

        self.send_button = ttk.Button(
            composer,
            text="Отправить",
            style="Primary.TButton",
            command=self.send_message,
        )
        self.send_button.grid(row=0, column=1, padx=(12, 0), sticky="ew")

        self.stop_button = ttk.Button(
            composer,
            text="Остановить",
            style="Secondary.TButton",
            command=self.stop_generation,
            state="disabled",
        )
        self.stop_button.grid(row=1, column=1, padx=(12, 0), pady=(7, 0), sticky="ew")

        status_row = ttk.Frame(self.chat_view)
        status_row.grid(row=3, column=0, sticky="ew", padx=22, pady=(0, 9))
        status_row.columnconfigure(0, weight=1)

        self.chat_status_var = tk.StringVar(
            value="Enter — отправить · Shift+Enter — новая строка"
        )
        ttk.Label(
            status_row,
            textvariable=self.chat_status_var,
            style="Subtitle.TLabel",
        ).grid(row=0, column=0, sticky="w")

    def _update_chat_header(self) -> None:
        config = self.config_data
        self.chat_title_var.set(config.model)
        self.chat_meta_var.set(
            f"{config.host}  ·  ctx {config.num_ctx}  ·  "
            f"temperature {config.temperature:g}"
        )

    def _clear_chat_widget(self) -> None:
        self.chat_text.configure(state="normal")
        self.chat_text.delete("1.0", "end")
        self.chat_text.configure(state="disabled")

    def _insert_chat(self, text: str, tag: str = "body") -> None:
        self.chat_text.configure(state="normal")
        self.chat_text.insert("end", text, tag)
        self.chat_text.configure(state="disabled")
        self.chat_text.see("end")

    def _append_system_notice(self, text: str) -> None:
        self._insert_chat(f"\n{text}\n", "system")

    def _append_user_message(self, text: str) -> None:
        self._insert_chat("\nВы\n", "user_header")
        self._insert_chat(text.strip() + "\n", "body")

    def _append_assistant_header(self) -> None:
        if not self.answer_header_visible:
            self._insert_chat("\nАссистент\n", "assistant_header")
            self.answer_header_visible = True

    def _append_thinking_header(self) -> None:
        if not self.thinking_header_visible:
            self._insert_chat("\nРассуждение модели\n", "thinking_header")
            self.thinking_header_visible = True

    def _on_enter(self, _event: tk.Event[Any]) -> str:
        self.send_message()
        return "break"

    @staticmethod
    def _on_shift_enter(_event: tk.Event[Any]) -> None:
        return None

    def send_message(self) -> None:
        if self.generation_active:
            return

        prompt = self.input_text.get("1.0", "end").strip()
        if not prompt:
            return

        if self.client is None:
            messagebox.showerror(
                "Чат не настроен",
                "Сначала примените настройки модели.",
                parent=self,
            )
            self._show_settings()
            return

        self.input_text.delete("1.0", "end")
        self._append_user_message(prompt)
        self.messages.append({"role": "user", "content": prompt})

        self.stop_event.clear()
        self.generation_active = True
        self.current_answer_parts = []
        self.current_thinking_parts = []
        self.answer_header_visible = False
        self.thinking_header_visible = False
        self.send_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.chat_status_var.set("Модель формирует ответ…")

        message_snapshot = [dict(message) for message in self.messages]
        threading.Thread(
            target=self._chat_worker,
            args=(message_snapshot,),
            daemon=True,
        ).start()

    def _chat_worker(self, message_snapshot: list[dict[str, str]]) -> None:
        assert self.client is not None
        config = self.config_data

        kwargs: dict[str, Any] = {
            "model": config.model,
            "messages": message_snapshot,
            "stream": True,
            "options": config.options(),
            "keep_alive": config.keep_alive,
        }
        if config.think is not None:
            kwargs["think"] = config.think

        try:
            try:
                stream = self.client.chat(**kwargs)
            except TypeError:
                # Совместимость со старыми версиями ollama-python,
                # в которых аргумент think ещё отсутствовал.
                if "think" not in kwargs:
                    raise
                kwargs.pop("think", None)
                self.events.put(
                    (
                        "notice",
                        "Установленный ollama-python не поддерживает параметр "
                        "think. Запрос отправлен без него.",
                    )
                )
                stream = self.client.chat(**kwargs)

            final_chunk: Any = None
            stopped = False

            for chunk in self._as_iterator(stream):
                final_chunk = chunk

                if self.stop_event.is_set():
                    stopped = True
                    break

                message = getattr(chunk, "message", None)
                if message is None and isinstance(chunk, dict):
                    message = chunk.get("message", {})

                content = self._message_field(message, "content")
                thinking = self._message_field(message, "thinking")

                if thinking:
                    self.events.put(("thinking", thinking))
                if content:
                    self.events.put(("content", content))

            stats = self._extract_stats(final_chunk)
            self.events.put(("done", {"stopped": stopped, "stats": stats}))

        except ResponseError as error:
            details = getattr(error, "error", None) or str(error)
            status = getattr(error, "status_code", None)
            if status == 404:
                details += (
                    f"\n\nМодель отсутствует. Выполните:\n"
                    f"ollama pull {config.model}"
                )
            self.events.put(("generation_error", details))
        except Exception as error:
            self.events.put(("generation_error", str(error)))

    @staticmethod
    def _as_iterator(stream: Any) -> Iterator[Any]:
        if hasattr(stream, "__iter__"):
            return iter(stream)
        return iter([stream])

    @staticmethod
    def _message_field(message: Any, field: str) -> str:
        if isinstance(message, dict):
            value = message.get(field, "")
        else:
            value = getattr(message, field, "")
        return str(value or "")

    @staticmethod
    def _extract_stats(chunk: Any) -> str:
        if chunk is None:
            return ""

        def get(name: str, default: Any = 0) -> Any:
            if isinstance(chunk, dict):
                return chunk.get(name, default)
            return getattr(chunk, name, default)

        eval_count = get("eval_count", 0) or 0
        eval_duration = get("eval_duration", 0) or 0
        prompt_count = get("prompt_eval_count", 0) or 0
        total_duration = get("total_duration", 0) or 0

        parts: list[str] = []
        if prompt_count:
            parts.append(f"контекст: {prompt_count} ток.")
        if eval_count:
            parts.append(f"ответ: {eval_count} ток.")
        if eval_count and eval_duration:
            tokens_per_second = eval_count / (eval_duration / 1_000_000_000)
            parts.append(f"{tokens_per_second:.1f} ток/с")
        if total_duration:
            parts.append(f"{total_duration / 1_000_000_000:.1f} с")
        return " · ".join(parts)

    def stop_generation(self) -> None:
        if self.generation_active:
            self.stop_event.set()
            self.chat_status_var.set("Остановка генерации…")

    def _finish_generation(self, *, stopped: bool, stats: str) -> None:
        answer = "".join(self.current_answer_parts).strip()
        thinking = "".join(self.current_thinking_parts).strip()

        if answer:
            self.messages.append({"role": "assistant", "content": answer})
        elif thinking and self.config_data.show_thinking:
            self._append_system_notice("Модель завершила запрос без итогового ответа.")
        elif stopped:
            self._append_system_notice("Генерация остановлена.")
        else:
            self._append_system_notice("Модель вернула пустой ответ.")

        self._insert_chat("\n", "body")
        self.generation_active = False
        self.send_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.input_text.focus_set()

        prefix = "Генерация остановлена"
        if not stopped:
            prefix = "Ответ завершён"
        self.chat_status_var.set(
            f"{prefix}" + (f" · {stats}" if stats else "")
        )

    def new_chat(self) -> None:
        if self.generation_active:
            messagebox.showwarning(
                "Идёт генерация",
                "Сначала остановите текущую генерацию.",
                parent=self,
            )
            return

        self.messages = [
            {
                "role": "system",
                "content": self.config_data.system_prompt,
            }
        ]
        self._clear_chat_widget()
        self._append_system_notice(
            f"Контекст очищен. Новый диалог с {self.config_data.model}."
        )
        self.chat_status_var.set(
            "Enter — отправить · Shift+Enter — новая строка"
        )
        self.input_text.focus_set()

    def export_chat(self) -> None:
        dialogue = [
            item for item in self.messages if item.get("role") != "system"
        ]
        if not dialogue:
            messagebox.showinfo(
                "Экспорт",
                "В текущем диалоге пока нет сообщений.",
                parent=self,
            )
            return

        default_name = (
            f"ollama_chat_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.md"
        )
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Экспортировать диалог",
            defaultextension=".md",
            initialfile=default_name,
            filetypes=[
                ("Markdown", "*.md"),
                ("JSON", "*.json"),
                ("Текст", "*.txt"),
            ],
        )
        if not path:
            return

        target = Path(path)
        try:
            if target.suffix.lower() == ".json":
                payload = {
                    "exported_at": datetime.now().isoformat(timespec="seconds"),
                    "config": asdict(self.config_data),
                    "messages": self.messages,
                }
                target.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            else:
                lines = [
                    f"# Диалог с {self.config_data.model}",
                    "",
                    f"- Сервер: `{self.config_data.host}`",
                    f"- Экспорт: {datetime.now().isoformat(timespec='seconds')}",
                    "",
                ]
                role_names = {"user": "Пользователь", "assistant": "Ассистент"}
                for item in dialogue:
                    role = role_names.get(item["role"], item["role"])
                    lines.extend(
                        [
                            f"## {role}",
                            "",
                            item["content"].strip(),
                            "",
                        ]
                    )
                target.write_text("\n".join(lines), encoding="utf-8")
        except OSError as error:
            messagebox.showerror(
                "Ошибка экспорта",
                str(error),
                parent=self,
            )
            return

        self.chat_status_var.set(f"Диалог сохранён: {target.name}")

    # ------------------------------------------------------------------
    # Обработка фоновых событий
    # ------------------------------------------------------------------

    def _process_events(self) -> None:
        while True:
            try:
                event, payload = self.events.get_nowait()
            except queue.Empty:
                break

            if event == "models":
                host, models = payload
                self.model_combo.configure(values=models)
                if models:
                    self.connection_status_var.set(
                        f"Ollama доступна: {host}. Найдено моделей: {len(models)}."
                    )
                    if not self.model_var.get().strip():
                        self.model_var.set(models[0])
                else:
                    self.connection_status_var.set(
                        "Ollama доступна, но локальные модели не найдены."
                    )

            elif event == "connection_ok":
                model, details = payload
                suffix = f" · {details}" if details else ""
                self.connection_status_var.set(
                    f"Подключение успешно · {model}{suffix}"
                )

            elif event == "model_missing":
                model, models = payload
                self.connection_status_var.set(
                    f"Модель «{model}» не установлена. "
                    f"Доступно моделей: {len(models)}."
                )
                messagebox.showwarning(
                    "Модель не найдена",
                    f"Установите модель командой:\n\nollama pull {model}",
                    parent=self,
                )

            elif event == "connection_error":
                self.connection_status_var.set(
                    f"Ошибка подключения: {payload}"
                )

            elif event == "notice":
                self._append_system_notice(str(payload))

            elif event == "thinking":
                text = str(payload)
                self.current_thinking_parts.append(text)
                if self.config_data.show_thinking:
                    self._append_thinking_header()
                    self._insert_chat(text, "thinking")

            elif event == "content":
                text = str(payload)
                self.current_answer_parts.append(text)
                self._append_assistant_header()
                self._insert_chat(text, "body")

            elif event == "done":
                self._finish_generation(
                    stopped=bool(payload.get("stopped")),
                    stats=str(payload.get("stats") or ""),
                )

            elif event == "generation_error":
                # Удаляем последнее пользовательское сообщение, чтобы
                # повторная отправка после исправления настроек не дублировала
                # испорченный ход диалога.
                if self.messages and self.messages[-1].get("role") == "user":
                    self.messages.pop()
                self.generation_active = False
                self.send_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
                self.chat_status_var.set("Ошибка генерации")
                self._append_system_notice(f"Ошибка: {payload}")
                messagebox.showerror(
                    "Ошибка Ollama",
                    str(payload),
                    parent=self,
                )

        self.after(60, self._process_events)

    # ------------------------------------------------------------------
    # Навигация и завершение
    # ------------------------------------------------------------------

    def _show_settings(self) -> None:
        self.chat_view.pack_forget()
        self.settings_view.pack(fill="both", expand=True)

    def _show_chat(self) -> None:
        if not self.chat_started:
            return
        self.settings_view.pack_forget()
        self.chat_view.pack(fill="both", expand=True)
        self.input_text.focus_set()

    def _on_close(self) -> None:
        if self.generation_active:
            self.stop_event.set()
            time.sleep(0.05)
        self.destroy()


def main() -> None:
    app = OllamaChatApp()
    app.mainloop()


if __name__ == "__main__":
    main()
