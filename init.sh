#!/bin/bash
set -e

WHITE='\033[0;37m'
BOLD_GREEN='\033[1;32m'

SCRIPTS_DIR="./scripts"

declare -A SCRIPT_LIST
declare -A SCRIPT_DESC
declare -A SCRIPT_FOLDER
declare -A FOLDER_ORDER

# Сканируем все скрипты
while IFS= read -r file; do
    ORDER=$(grep -m1 '^# ORDER:' "$file" | awk -F: '{print $2}' | xargs)
    DESC=$(grep -m1 '^# DESC:' "$file" | cut -d':' -f2- | xargs)
    REL_PATH="${file#$SCRIPTS_DIR/}"
    FOLDER=$(dirname "$REL_PATH")

    [[ -z "$ORDER" ]] && ORDER=9999

    SCRIPT_LIST["$FOLDER:$ORDER:$REL_PATH"]="$file"
    SCRIPT_DESC["$FOLDER:$ORDER:$REL_PATH"]="$DESC"
    SCRIPT_FOLDER["$FOLDER:$ORDER:$REL_PATH"]="$FOLDER"

    [[ -z "${FOLDER_ORDER[$FOLDER]}" ]] && FOLDER_ORDER["$FOLDER"]=9999
done < <(find "$SCRIPTS_DIR" -type f -name "*.sh")

# Ручной порядок папок:
FOLDER_ORDER["dev"]=1
FOLDER_ORDER["db"]=2
FOLDER_ORDER["."]=3
FOLDER_ORDER["prod"]=4

# Собираем меню скриптов с учётом сортировки папок и ORDER
declare -a MENU
count=1
for FOLDER in $(for f in "${!FOLDER_ORDER[@]}"; do
    echo "${FOLDER_ORDER[$f]}:$f"
done | sort -n | cut -d: -f2); do

    CURRENT_FOLDER="$FOLDER"

    for key in $(printf '%s\n' "${!SCRIPT_LIST[@]}" | grep "^$FOLDER:" | sort -t: -k2,2n); do
        FILE_PATH="${SCRIPT_LIST[$key]}"
        DESC="${SCRIPT_DESC[$key]}"

        if [[ "$FIRST_FOLDER_SHOWN" != "$CURRENT_FOLDER" ]]; then
            echo -e "  ${BOLD_GREEN}$CURRENT_FOLDER${WHITE}:"
            FIRST_FOLDER_SHOWN="$CURRENT_FOLDER"
        fi

        echo "    $count) $(basename "$FILE_PATH")"
        echo "       $DESC"
        MENU[$count]="$FILE_PATH"
        ((count++))
    done
done

# Если переданы аргументы-числа — запускаем указанные скрипты
if [[ $# -gt 0 ]]; then
    for CHOICE in "$@"; do
        if [[ ! "$CHOICE" =~ ^[0-9]+$ ]] || [[ -z "${MENU[$CHOICE]}" ]]; then
            echo "Ошибка: скрипт с номером $CHOICE не найден"
            exit 1
        fi
        echo -e "\nЗапускаем ${MENU[$CHOICE]}..."
        bash "${MENU[$CHOICE]}"
    done
    exit 0
fi

# Если аргументов нет — показываем меню для выбора одного скрипта
echo
read -rp "Введите номер скрипта для запуска: " CHOICE
if [[ -z "${MENU[$CHOICE]}" ]]; then
    echo "Ошибка: выбран некорректный номер"
    exit 1
fi

echo "Запускаем ${MENU[$CHOICE]}..."
bash "${MENU[$CHOICE]}"
