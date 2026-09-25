#!/bin/bash
# ORDER: 20
# DESC: Слить все out/*.txt в один файл с уникальными строками
source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.bash"

shopt -s nullglob
files=("$PROJECT_ROOT/out"/*.txt)
shopt -u nullglob

(( ${#files[@]} )) || fail "в $PROJECT_ROOT/out нет ни одного .txt — сначала запустите поиск"

TARGET="${1:-$PROJECT_ROOT/out/all.txt}"

info "сливаю файлов: ${#files[@]}"
note "источники: ${files[*]##*/}"
info "цель: $TARGET"

# sort -u, а не set в памяти: миллионы строк он разбирает через временные файлы.
cat "${files[@]}" | sort -u > "$TARGET.tmp"
mv "$TARGET.tmp" "$TARGET"

info "строк после дедупликации: $(wc -l < "$TARGET")"
note "формат прежний: строка на запись, у CT-маршрута «адрес<TAB>имя»"
