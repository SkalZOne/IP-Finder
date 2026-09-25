#!/bin/bash
# ORDER: 20
# DESC: Проверить синтаксис всех Python-файлов
source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.bash"
require_venv

"$VENV_PYTHON" -m compileall -q "$PROJECT_ROOT/src" "$PROJECT_ROOT/tests" \
    && info "синтаксис в порядке: src и tests"
