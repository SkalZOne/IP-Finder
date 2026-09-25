#!/bin/bash
# ORDER: 30
# DESC: Удалить __pycache__ и .pyc внутри проекта
source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.bash"

find "$PROJECT_ROOT/src" "$PROJECT_ROOT/tests" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
info "кэши байткода удалены"
