UV ?= uv
APP ?= ollama_gui_logged.py
MODEL ?= qwen3.5:9b
INDEX ?= https://pypi.org/simple
LOG_LEVEL ?= INFO

.DEFAULT_GOAL := help

.PHONY: help setup sync lock run run-gui run-debug run-debug-content doctor check \
        compile lint test format format-check models pull-model serve tree upgrade \
        export-requirements reset repair-index log-path open-logs clear-logs

help: ## Показать доступные команды
	@echo "Ollama GUI Chat — команды проекта"
	@echo ""
	@echo "  make setup               Создать .venv и установить зависимости"
	@echo "  make run                 Запустить GUI, уровень логов LOG_LEVEL=$(LOG_LEVEL)"
	@echo "  make run-gui             Запустить GUI без консольного окна (Windows)"
	@echo "  make run-debug           Запустить с подробными DEBUG-логами"
	@echo "  make run-debug-content   DEBUG + полный текст запросов и ответов"
	@echo "  make log-path            Показать путь к основному журналу"
	@echo "  make open-logs           Открыть каталог журналов в Проводнике"
	@echo "  make clear-logs          Удалить созданные журналы"
	@echo "  make doctor              Проверить Python, Tkinter, Ollama и модель"
	@echo "  make check               Компиляция, тесты и статическая проверка"
	@echo "  make test                Запустить unit-тесты логирования"
	@echo "  make pull-model          Скачать модель MODEL=$(MODEL)"
	@echo "  make models              Показать локальные модели Ollama"
	@echo "  make serve               Запустить сервер Ollama"
	@echo "  make lock                Обновить uv.lock через публичный PyPI"
	@echo "  make repair-index        Исправить lock-файл со служебным индексом"

setup: sync ## Первичная настройка проекта

sync: ## Синхронизировать .venv с pyproject.toml и uv.lock
	$(UV) sync --default-index $(INDEX)

lock: ## Пересобрать lock-файл без принудительного обновления версий
	$(UV) lock --default-index $(INDEX)

run: ## Запустить приложение
	$(UV) run python $(APP) --log-level $(LOG_LEVEL)

run-gui: ## Запустить приложение через pythonw (Windows, без консоли)
	$(UV) run pythonw $(APP) --log-level $(LOG_LEVEL)

run-debug: ## Запустить с максимально подробным техническим журналом
	$(UV) run python $(APP) --log-level DEBUG

run-debug-content: ## Запустить DEBUG-режим с записью полного текста диалога
	$(UV) run python $(APP) --log-level DEBUG --log-content

log-path: ## Показать путь к основному журналу
	$(UV) run python -c "from ollama_gui_logged import DEFAULT_LOG_FILE; print(DEFAULT_LOG_FILE)"

open-logs: ## Открыть каталог журналов
	$(UV) run python -c "from ollama_gui_logged import open_log_directory; open_log_directory()"

clear-logs: ## Удалить журналы; приложение должно быть закрыто
	$(UV) run python -c "import shutil; from ollama_gui_logged import LOG_DIR; shutil.rmtree(LOG_DIR, ignore_errors=True); LOG_DIR.mkdir(parents=True, exist_ok=True); print('Журналы очищены:', LOG_DIR)"

doctor: ## Проверить локальное окружение и интеграцию
	$(UV) --version
	$(UV) run python --version
	$(UV) run python -c "import tkinter; print('Tkinter OK, Tcl/Tk', tkinter.TclVersion)"
	$(UV) run python -c "import ollama; print('ollama-python OK')"
	$(UV) run python -c "from ollama_gui_logged import DEFAULT_LOG_FILE; print('Log file:', DEFAULT_LOG_FILE)"
	ollama --version
	ollama list

check: compile lint test ## Выполнить безопасные проверки проекта

compile: ## Проверить синтаксис Python
	$(UV) run python -m py_compile ollama_gui_chat.py ollama_gui_logged.py

lint: ## Запустить Ruff
	$(UV) run ruff check ollama_gui_chat.py ollama_gui_logged.py tests

test: ## Запустить unit-тесты логирования
	$(UV) run python -m unittest discover -s tests -v

format: ## Отформатировать Python-код
	$(UV) run ruff format ollama_gui_logged.py tests

format-check: ## Проверить форматирование без изменения файлов
	$(UV) run ruff format --check ollama_gui_logged.py tests

models: ## Показать загруженные модели
	ollama list

pull-model: ## Загрузить выбранную модель Ollama
	ollama pull $(MODEL)

serve: ## Запустить Ollama API в текущем терминале
	ollama serve

tree: ## Показать дерево зависимостей
	$(UV) tree

upgrade: ## Обновить lock-файл и окружение
	$(UV) lock --upgrade --default-index $(INDEX)
	$(UV) sync --default-index $(INDEX)

export-requirements: ## Создать совместимый requirements.txt
	$(UV) export --format requirements-txt --no-hashes --output-file requirements.txt

reset: ## Переустановить зависимости в текущем окружении
	$(UV) sync --reinstall --default-index $(INDEX)

repair-index: ## Пересоздать lock-файл через публичный PyPI (Windows PowerShell)
	powershell -NoProfile -ExecutionPolicy Bypass -File ./repair_uv.ps1
