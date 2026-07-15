UV ?= uv
PYTHON ?= python
APP ?= ollama_gui_chat.py
MODEL ?= qwen3.5:9b
INDEX ?= https://pypi.org/simple

.DEFAULT_GOAL := help

.PHONY: help setup sync lock run run-gui doctor check compile lint format format-check \
        models pull-model serve tree upgrade export-requirements reset repair-index

help: ## Показать доступные команды
	@echo "Ollama GUI Chat — команды проекта"
	@echo ""
	@echo "  make setup               Создать .venv и установить зависимости"
	@echo "  make run                 Запустить GUI с консолью"
	@echo "  make run-gui             Запустить GUI без консольного окна (Windows)"
	@echo "  make doctor              Проверить Python, Tkinter, Ollama и модель"
	@echo "  make check               Компиляция и статическая проверка"
	@echo "  make pull-model          Скачать модель MODEL=$(MODEL)"
	@echo "  make models              Показать локальные модели Ollama"
	@echo "  make serve               Запустить сервер Ollama"
	@echo "  make lock                Обновить uv.lock через публичный PyPI"
	@echo "  make repair-index        Исправить lock-файл со служебным индексом"
	@echo "  make upgrade             Обновить зависимости в допустимых пределах"
	@echo "  make format              Форматировать Python-код"
	@echo "  make export-requirements Экспортировать requirements.txt из uv.lock"
	@echo ""
	@echo "Пример другой модели: make pull-model MODEL=qwen3.5:9b"

setup: sync ## Первичная настройка проекта

sync: ## Синхронизировать .venv с pyproject.toml и uv.lock
	$(UV) sync --default-index $(INDEX)

lock: ## Пересобрать lock-файл без принудительного обновления версий
	$(UV) lock --default-index $(INDEX)

run: ## Запустить приложение
	$(UV) run python $(APP)

run-gui: ## Запустить приложение через pythonw (Windows, без консоли)
	$(UV) run pythonw $(APP)

doctor: ## Проверить локальное окружение и интеграцию
	$(UV) --version
	$(UV) run python --version
	$(UV) run python -c "import tkinter; print('Tkinter OK, Tcl/Tk', tkinter.TclVersion)"
	$(UV) run python -c "import ollama; print('ollama-python OK')"
	ollama --version
	ollama list

check: compile lint ## Выполнить безопасные проверки проекта

compile: ## Проверить синтаксис Python
	$(UV) run python -m py_compile $(APP)

lint: ## Запустить Ruff
	$(UV) run ruff check $(APP)

format: ## Отформатировать Python-код
	$(UV) run ruff format $(APP)

format-check: ## Проверить форматирование без изменения файлов
	$(UV) run ruff format --check $(APP)

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
