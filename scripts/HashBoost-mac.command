#!/bin/bash
# Запуск HashBoost на macOS в режиме симуляции (двойной клик в Finder).
#
# Скрипт сам готовит всё, что нужно:
#   1. ищет установленный Python 3.10–3.14 (на 3.15 ещё нет сборок numpy и Qt);
#   2. если такого нет — ставит Python 3.13 через Homebrew, а без Homebrew —
#      через uv в домашнюю папку (без пароля администратора);
#   3. создаёт окружение .venv и ставит зависимости;
#   4. проверяет, что всё импортируется, и при поломке пересоздаёт окружение.
set -e
cd "$(dirname "$0")/.."

TARGET="3.13"
SUPPORTED="3.14 3.13 3.12 3.11 3.10"
STAMP=".venv/.hashboost-ready"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

say() { echo "▸ $*"; }

fail() {
    echo
    echo "Не получилось подготовить запуск: $*"
    echo "Скопируйте текст из этого окна и пришлите его — разберёмся."
    read -r -p "Нажмите Enter, чтобы закрыть окно"
    exit 1
}

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

deps_ok() {
    [ -x .venv/bin/python ] && is_supported .venv/bin/python &&
        .venv/bin/python -c 'import numpy, pyqtgraph, PySide6.QtWidgets, hashboost' 2>/dev/null
}

get_uv() {
    if ! command -v uv >/dev/null 2>&1; then
        say "Ставлю uv (менеджер Python) в ~/.local/bin..."
        curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null || return 1
    fi
    command -v uv >/dev/null 2>&1
}

build_env() {
    rm -rf .venv
    local py
    if py=$(find_python); then
        say "Создаю окружение на $($py -V)..."
        "$py" -m venv .venv && .venv/bin/python -m pip install -q --upgrade pip &&
            .venv/bin/python -m pip install -q -e . && return 0
    elif command -v brew >/dev/null 2>&1; then
        say "Подходящего Python нет, ставлю Python $TARGET через Homebrew..."
        if brew install "python@$TARGET" && py=$(find_python); then
            "$py" -m venv .venv && .venv/bin/python -m pip install -q --upgrade pip &&
                .venv/bin/python -m pip install -q -e . && return 0
        fi
    fi
    # Запасной путь: uv сам скачает Python и поставит зависимости
    say "Готовлю окружение через uv (Python $TARGET скачается автоматически)..."
    rm -rf .venv
    get_uv || return 1
    uv venv -q --python "$TARGET" .venv && uv pip install -q --python .venv/bin/python -e .
}

if [ ! -f "$STAMP" ] || ! deps_ok; then
    [ -d .venv ] && say "Окружение неполное или собрано не той версией Python — пересоздаю."
    [ -d .venv ] || say "Первый запуск: готовлю окружение, это займёт пару минут."
    build_env || fail "установка зависимостей завершилась ошибкой"
    if ! deps_ok; then
        say "Проверка не прошла, пробую ещё раз через uv..."
        rm -rf .venv
        get_uv || fail "не удалось установить uv (нет интернета?)"
        uv venv -q --python "$TARGET" .venv && uv pip install -q --python .venv/bin/python -e . ||
            fail "установка через uv завершилась ошибкой"
        deps_ok || fail "зависимости не импортируются"
    fi
    touch "$STAMP"
    say "Готово, запускаю HashBoost."
fi

exec .venv/bin/python -m hashboost --simulate "$@"
