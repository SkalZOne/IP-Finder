#!/bin/bash
# ORDER: 20
# DESC: Создать .env с путями к out/ и data/ (необязательно)
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.bash"

if [[ -f "$PROJECT_ROOT/.env" ]]; then
    info ".env уже есть, не перезаписываю: $PROJECT_ROOT/.env"
else
    cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
    info "создан .env из .env.example"
fi

echo
note "файл необязательный: без него результаты идут в out/, а кэш и курсоры — в data/,"
note "то есть внутрь $PROJECT_ROOT. Нужны другие каталоги — раскомментируйте строки в .env."
