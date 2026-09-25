#!/bin/bash
# ORDER: 10
# DESC: Python-REPL с готовыми импортами пайплайна
source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.bash"
require_deps

info "интерактивная сессия: store, normalize, sources уже импортированы, выход — Ctrl+D"
exec "$VENV_PYTHON" -i -c "from src.pipeline import normalize, sources, store"
