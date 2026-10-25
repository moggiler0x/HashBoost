#!/bin/bash
# Запуск HashBoost на macOS в режиме симуляции (двойной клик в Finder).
# При первом запуске создаёт окружение .venv рядом с проектом и ставит зависимости.
# Нужен Python 3.10–3.14: для более новых версий ещё нет готовых сборок numpy и Qt.
set -e
cd "$(dirname "$0")/.."

SUPPORTED="3.14 3.13 3.12 3.11 3.10"

is_supported() {
    "$1" -c 'import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] < (3, 15) else 1)' 2>/dev/null
}

find_python() {
    for v in $SUPPORTED; do
        for p in "python$v" "/opt/homebrew/bin/python$v" "/usr/local/bin/python$v" \
                 "/Library/Frameworks/Python.framework/Versions/$v/bin/python$v"; do
            if command -v "$p" >/dev/null 2>&1 && is_supported "$p"; then
                echo "$p"
                return 0
            fi
        done
    done
    if command -v python3 >/dev/null 2>&1 && is_supported python3; then
        echo python3
        return 0
    fi
    return 1
}

# Окружение, созданное неподходящим Python, пересоздаём
if [ -x .venv/bin/python ] && ! is_supported .venv/bin/python; then
    echo "Окружение .venv создано неподходящей версией Python ($(.venv/bin/python -V 2>&1)), пересоздаю..."
    rm -rf .venv
fi

if [ ! -d .venv ]; then
    if ! PY=$(find_python); then
        echo "Не найден подходящий Python (нужна версия от 3.10 до 3.14)."
        echo "Сейчас установлен: $(python3 -V 2>&1 || echo 'нет python3')"
        echo "Установите Python 3.13: brew install python@3.13"
        echo "или скачайте установщик 3.13 с https://www.python.org/downloads/macos/"
        read -r -p "Нажмите Enter, чтобы закрыть окно"
        exit 1
    fi
    echo "Первый запуск: создаю окружение на $($PY -V) и ставлю зависимости..."
    "$PY" -m venv .venv
    .venv/bin/pip install --upgrade pip >/dev/null
    .venv/bin/pip install -e .
fi

exec .venv/bin/python -m hashboost --simulate "$@"
