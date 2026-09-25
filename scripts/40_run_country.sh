#!/bin/bash
# ORDER: 40
# DESC: Найти IP-адреса по коду страны
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.bash"
require_deps

if [[ $# -eq 0 ]]; then
    note "аргументов нет — пробный прогон по Лихтенштейну, без записи в файл"
    note "свой запуск: bash scripts/40_run_country.sh DE --max-addresses 5000"
    set -- LI --per-prefix 3 --max-addresses 12 --limit 12 --no-save
fi

info "python -m src.main $*"
exec "$VENV_PYTHON" -m src.main "$@"
