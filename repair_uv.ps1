$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$PublicIndex = "https://pypi.org/simple"
$InternalHost = "packages.applied-caas-gateway1.internal.api.openai.org"

Write-Host "Проверка переменных окружения uv/pip..." -ForegroundColor Cyan
foreach ($Name in @("UV_DEFAULT_INDEX", "UV_INDEX_URL", "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL")) {
    $Value = [Environment]::GetEnvironmentVariable($Name, "Process")
    if ($Value -and $Value.Contains($InternalHost)) {
        Write-Host "Удалена переменная процесса $Name=$Value" -ForegroundColor Yellow
        Remove-Item "Env:$Name" -ErrorAction SilentlyContinue
    }
}

if (Test-Path ".venv") {
    Write-Host "Удаление старого виртуального окружения .venv..." -ForegroundColor Cyan
    Remove-Item ".venv" -Recurse -Force
}

Write-Host "Проверка lock-файла..." -ForegroundColor Cyan
if (Test-Path "uv.lock") {
    $LockContent = Get-Content "uv.lock" -Raw
    if ($LockContent.Contains($InternalHost)) {
        Write-Host "Удаление lock-файла со служебным индексом..." -ForegroundColor Yellow
        Remove-Item "uv.lock" -Force
    }
}

Write-Host "Создание uv.lock через публичный PyPI..." -ForegroundColor Cyan
uv lock --default-index $PublicIndex

Write-Host "Установка зависимостей..." -ForegroundColor Cyan
uv sync --default-index $PublicIndex

Write-Host "Готово. Запуск: uv run python ollama_gui_chat.py" -ForegroundColor Green
