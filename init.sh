#!/bin/bash
source "$(dirname "${BASH_SOURCE[0]}")/scripts/lib/common.bash"

WHITE='\033[0;37m'
BOLD_GREEN='\033[1;32m'

SCRIPTS_DIR="./scripts"

declare -A SCRIPT_LIST
declare -A SCRIPT_DESC

while IFS= read -r file; do
    ORDER=$(sed -n 's/^# ORDER:[[:space:]]*//p' "$file" | head -n 1)
    DESC=$(sed -n 's/^# DESC:[[:space:]]*//p' "$file" | head -n 1)
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

run_choice() {
    local choice="$1" file kind
    if [[ ! "$choice" =~ ^[1-9][0-9]*$ ]] || [[ -z "${MENU[$choice]:-}" ]]; then
        echo "Ошибка: скрипт с номером $choice не найден" >&2
        return 1
    fi

    file="${MENU[$choice]}"
    if [[ "$(basename "$file")" == 40_run_country.sh || "$(basename "$file")" == 50_run_ct.sh || "$(basename "$file")" == 55_run_shodan.sh ]]; then
        kind=country
        [[ "$(basename "$file")" == 50_run_ct.sh ]] && kind=ct
        [[ "$(basename "$file")" == 55_run_shodan.sh ]] && kind=shodan
        prompt_script_args "$kind" || return 1
        echo -e "\nЗапускаем $file..."
        IPFINDER_ARGS_PROMPTED=1 bash "$file" "${PROMPTED_ARGS[@]}"
    else
        echo -e "\nЗапускаем $file..."
        bash "$file"
    fi
}

if [[ $# -gt 0 ]]; then
    for choice in "$@"; do
        run_choice "$choice"
    done
    exit 0
fi

echo
read -rp "Введите номер скрипта для запуска: " choice
run_choice "$choice"
