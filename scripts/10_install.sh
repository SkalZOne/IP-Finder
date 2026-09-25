#!/bin/bash
# ORDER: 10
# DESC: Создать venv и установить зависимости
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.bash"

PY="${PYTHON_BIN:-python3}"
command -v "$PY" >/dev/null 2>&1 || fail "не найден $PY — укажите интерпретатор: PYTHON_BIN=python3.13 $0"

info "интерпретатор: $("$PY" --version 2>&1) ($PY)"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
    || fail "нужен Python 3.10 или новее: код использует современный синтаксис типов"

if [[ -d "$VENV_DIR" ]]; then
    note "venv уже существует: $VENV_DIR"
else
    info "создаю venv: $VENV_DIR"
    "$PY" -m venv "$VENV_DIR"
fi

info "обновляю pip"
"$VENV_PYTHON" -m pip install --quiet --upgrade pip

info "устанавливаю зависимости из requirements.txt"
"$VENV_PYTHON" -m pip install --quiet -r "$PROJECT_ROOT/requirements.txt"

info "готово"
"$VENV_PYTHON" -c 'import sys, requests, dotenv; print("  python:", sys.version.split()[0]); print("  requests:", requests.__version__)'
note "дальше: scripts/30_check.sh — проверить окружение, затем scripts/40_run_country.sh"
