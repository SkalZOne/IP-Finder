#!/bin/bash
set -e

WHITE='\033[0;37m'
BOLD_GREEN='\033[1;32m'

SCRIPTS_DIR="./scripts"

declare -A SCRIPT_LIST
declare -A SCRIPT_DESC

while IFS= read -r file; do
    ORDER=$(grep -m1 '^# ORDER:' "$file" | awk -F: '{print $2}' | xargs)
    DESC=$(grep -m1 '^# DESC:' "$file" | cut -d':' -f2- | xargs)
    [[ -z "$ORDER" ]] && ORDER=9999

    key="$ORDER:$(basename "$file")"
    SCRIPT_LIST["$key"]="$file"
    SCRIPT_DESC["$key"]="$DESC"
done < <(find "$SCRIPTS_DIR" -maxdepth 1 -type f -name "*.sh")

declare -a MENU
count=1

echo -e "  ${BOLD_GREEN}IP-finder${WHITE}:"
while IFS= read -r key; do
    file="${SCRIPT_LIST[$key]}"
    echo "    $count) $(basename "$file")"
    echo "       ${SCRIPT_DESC[$key]}"
    MENU[$count]="$file"
    ((count++))
done < <(printf '%s\n' "${!SCRIPT_LIST[@]}" | sort -t: -k1,1n -k2,2)

if [[ $# -gt 0 ]]; then
    for choice in "$@"; do
        if [[ ! "$choice" =~ ^[0-9]+$ ]] || [[ -z "${MENU[$choice]}" ]]; then
            echo "Ошибка: скрипт с номером $choice не найден"
            exit 1
        fi
        echo -e "\nЗапускаем ${MENU[$choice]}..."
        bash "${MENU[$choice]}"
    done
    exit 0
fi

echo
read -rp "Введите номер скрипта для запуска: " choice
if [[ ! "$choice" =~ ^[0-9]+$ ]] || [[ -z "${MENU[$choice]}" ]]; then
    echo "Ошибка: выбран некорректный номер"
    exit 1
fi

echo "Запускаем ${MENU[$choice]}..."
bash "${MENU[$choice]}"
