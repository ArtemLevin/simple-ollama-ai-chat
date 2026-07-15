# Ollama GUI Chat

Desktop-интерфейс для локальных моделей Ollama с предварительной настройкой модели, потоковым выводом и расширенной диагностикой.

## Возможности

- выбор локальной модели и адреса Ollama API;
- системный промпт и готовые ролевые профили;
- настройка `temperature`, `top_p`, `top_k`, `min_p` и штрафов повторения;
- размер контекста, лимит ответа, `seed`, `keep_alive` и режим рассуждения;
- потоковая генерация, остановка ответа, очистка контекста и экспорт диалога;
- файловое и консольное логирование с ротацией;
- идентификатор сессии и отдельный идентификатор генерации;
- трассировка фоновых потоков, подключений, запросов и ошибок Tkinter;
- безопасное логирование содержимого через длину и SHA-256-отпечаток;
- диагностическое меню в GUI для открытия каталога журналов.

## Требования

- Windows 10/11;
- Python 3.11–3.14 с Tkinter;
- `uv`;
- Ollama;
- GNU Make — опционально.

Проверка Tkinter:

```powershell
python -c "import tkinter; print(tkinter.TclVersion)"
```

## Первый запуск

```powershell
uv sync --default-index https://pypi.org/simple
ollama pull qwen3.5:9b
uv run python ollama_gui_logged.py
```

Через Makefile:

```powershell
make setup
make pull-model
make doctor
make run
```

## Расширенное логирование

Основной журнал:

```text
%USERPROFILE%\.ollama_desktop_chat\logs\ollama_gui_chat.log
```

Используется ротация по 5 МБ и хранение пяти архивных файлов.

Обычный запуск с уровнем `INFO`:

```powershell
make run
```

Подробная диагностика:

```powershell
make run-debug
```

По умолчанию тексты запросов и ответов скрыты: в DEBUG-журнал попадают длина, число строк и SHA-256-отпечаток. Для локальной глубокой диагностики можно явно включить запись содержимого:

```powershell
make run-debug-content
```

Этот режим записывает полный текст диалога и рассуждений модели. Перед передачей журнала третьим лицам проверьте его содержимое.

Путь к журналу и каталог логов:

```powershell
make log-path
make open-logs
```

Удаление журналов после закрытия приложения:

```powershell
make clear-logs
```

## Проверки

```powershell
make check
```

Команда выполняет:

```text
python -m py_compile ollama_gui_chat.py ollama_gui_logged.py
ruff check ollama_gui_chat.py ollama_gui_logged.py tests
python -m unittest discover -s tests -v
```

## Публичный PyPI

`pyproject.toml` закрепляет публичный индекс `https://pypi.org/simple`. Если старый `uv.lock` содержит служебный адрес пакетного зеркала, выполните:

```powershell
powershell -ExecutionPolicy Bypass -File .\repair_uv.ps1
```

## Почему используется системный Python

```toml
[tool.uv]
python-preference = "only-system"
```

Tkinter использует Tcl/Tk из обычного установщика Python для Windows. Настройка предотвращает автоматическую подмену интерпретатора сборкой без подходящей конфигурации Tkinter.
