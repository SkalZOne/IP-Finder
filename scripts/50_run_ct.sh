#!/bin/bash
# ORDER: 50
# DESC: Найти IP-адреса домена через CT-журналы
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.bash"
require_deps

if [[ $# -eq 0 && -t 0 && "${IPFINDER_ARGS_PROMPTED:-0}" != 1 ]]; then
    prompt_script_args ct || exit 1
    set -- "${PROMPTED_ARGS[@]}"
fi

if [[ $# -eq 0 ]]; then
    note "аргументов нет — пример на example.org, без записи в файл"
    note "свой запуск: bash scripts/50_run_ct.sh --ct my-domain.ru --max-addresses 200"
    set -- --ct example.org --limit 10 --no-save
fi

info "python -m src.main $*"
exec "$VENV_PYTHON" -m src.main "$@"
