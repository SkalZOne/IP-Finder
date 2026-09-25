#!/bin/bash
# ORDER: 60
# DESC: Запустить тесты
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.bash"
require_venv

info "тесты: база не нужна, хранилище подменяется временным каталогом"
exec "$VENV_PYTHON" -m unittest discover -s tests -v
