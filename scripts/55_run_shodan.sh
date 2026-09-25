#!/bin/bash
# ORDER: 55
# DESC: Найти IP-адреса через Shodan
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.bash"
require_deps

if [[ $# -eq 0 && -t 0 && "${IPFINDER_ARGS_PROMPTED:-0}" != 1 ]]; then
    prompt_script_args shodan || exit 1
    set -- "${PROMPTED_ARGS[@]}"
fi

if [[ $# -eq 0 ]]; then
    fail "укажите запрос: --shodan 'nginx country:DE' (ключ задаётся через SHODAN_API_KEY)"
fi

info "python -m src.main $*"
exec "$VENV_PYTHON" -m src.main "$@"
