#!/bin/bash
# ORDER: 40
# DESC: Найти IP-адреса по стране или ASN
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.bash"
require_deps

if [[ $# -eq 0 && -t 0 && "${IPFINDER_ARGS_PROMPTED:-0}" != 1 ]]; then
    prompt_script_args country || exit 1
    set -- "${PROMPTED_ARGS[@]}"
fi

if [[ $# -eq 0 ]]; then
    note "аргументов нет — пробный прогон по Лихтенштейну, без записи в файл"
    note "свой запуск: bash scripts/40_run_country.sh DE --max-addresses 5000"
    set -- LI --per-prefix 3 --max-addresses 12 --limit 12 --no-save
fi

info "python -m src.main $*"
exec "$VENV_PYTHON" -m src.main "$@"
