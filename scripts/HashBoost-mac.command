#!/bin/bash
# Запуск HashBoost на macOS в режиме симуляции (двойной клик в Finder).
# При первом запуске создаёт окружение .venv рядом с проектом и ставит зависимости.
set -e
cd "$(dirname "$0")/.."

if ! command -v python3 >/dev/null 2>&1; then
    echo "Не найден python3. Установите Python 3.10+ с python.org или через Homebrew: brew install python"
    read -r -p "Нажмите Enter, чтобы закрыть окно"
    exit 1
fi

if [ ! -d .venv ]; then
    echo "Первый запуск: создаю окружение и ставлю зависимости..."
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip >/dev/null
    .venv/bin/pip install -e .
fi

exec .venv/bin/python -m hashboost --simulate "$@"
