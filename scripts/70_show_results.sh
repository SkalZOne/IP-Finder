#!/bin/bash
# ORDER: 70
# DESC: Показать последний файл с результатами (число строк — первый аргумент)
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.bash"

LIMIT="${1:-20}"
OUT_DIR="$PROJECT_ROOT/out"

shopt -s nullglob
files=("$OUT_DIR"/*.txt)
shopt -u nullglob

if (( ${#files[@]} == 0 )); then
    warn "в $OUT_DIR пока пусто — сначала запустите поиск (scripts/40_run_country.sh)"
    exit 1
fi

latest="$(ls -1t "${files[@]}" | head -1)"
lines="$(wc -l < "$latest")"

info "последний файл: $latest"
note "строк в нём: $lines; файлов в out/: ${#files[@]}"
echo
head -n "$LIMIT" "$latest" | sed 's/^/    /'

if (( lines > LIMIT )); then
    note "    ...и ещё $((lines - LIMIT))"
fi
