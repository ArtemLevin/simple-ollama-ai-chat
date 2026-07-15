# Ollama GUI Chat

Desktop-интерфейс для диалога с локальными моделями Ollama. Перед открытием чата можно настроить системный промпт, sampling, размер контекста, лимит ответа и режим рассуждения.

## Требования

- Windows 10/11;
- установленный обычный Python 3.13 с поддержкой Tkinter;
- `uv`;
- Ollama;
- GNU Make — только для сокращённых команд из `Makefile`.

Проверка Tkinter:

```powershell
python -c "import tkinter; print(tkinter.TclVersion)"
```

## Установка uv

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uv --version
```

После установки перезапустите PowerShell, если команда `uv` ещё не обнаруживается.

## Первый запуск через uv

```powershell
uv sync
ollama pull qwen3.5:9b
uv run python ollama_gui_chat.py
```

Активация `.venv` для `uv run` не требуется. `uv` сам создаёт и синхронизирует окружение.

## Запуск через Makefile

```powershell
make setup
make pull-model
make doctor
make run
```

Запуск без консольного окна в Windows:

```powershell
make run-gui
```

Другая модель:

```powershell
make pull-model MODEL=qwen3.5:9b
```

## Основные команды

| Команда | Назначение |
|---|---|
| `make setup` | создать `.venv` и установить зависимости |
| `make run` | запустить приложение |
| `make doctor` | проверить Python, Tkinter, Ollama и модели |
| `make check` | проверить синтаксис и код через Ruff |
| `make lock` | обновить `uv.lock` |
| `make upgrade` | обновить версии зависимостей в lock-файле |
| `make export-requirements` | создать обычный `requirements.txt` |

## Если `make` отсутствует

Все цели имеют прямой эквивалент в `uv`. Для повседневной работы достаточно:

```powershell
uv sync
uv run python ollama_gui_chat.py
```

На Windows GNU Make можно установить через Chocolatey:

```powershell
choco install make
```

После установки откройте новый терминал.

## Почему используется системный Python

`pyproject.toml` содержит:

```toml
[tool.uv]
python-preference = "only-system"
```

GUI построен на Tkinter, которому нужны Tcl/Tk. Обычный установщик Python для Windows включает эти компоненты. Настройка запрещает `uv` незаметно выбрать другой managed-интерпретатор без подходящей конфигурации Tkinter.
