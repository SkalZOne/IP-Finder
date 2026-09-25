#!/bin/bash
# ORDER: 60
# DESC: Прогнать тесты (база не нужна, всё работает на файлах)
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.bash"
require_venv

info "тесты: база не нужна, хранилище подменяется временным каталогом"
exec "$VENV_PYTHON" -m unittest discover -s tests -v
