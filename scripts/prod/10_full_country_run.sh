#!/bin/bash
# ORDER: 10
# DESC: Полный прогон страны с записью в файл (спрашивает подтверждение)
source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.bash"
require_deps

# Прогон долгий и пишет результат целиком, поэтому без живого терминала не
# запускаемся: так случайный номер из меню не уедет в многомиллионный обход.
if [[ ! -t 0 ]]; then
    fail "нужен интерактивный ввод — прогон идёт долго и пишет файл"
fi

read -rp "Код страны из двух букв (например DE): " COUNTRY
[[ "$COUNTRY" =~ ^[A-Za-z]{2}$ ]] || fail "нужен код из двух букв, получено: ${COUNTRY:-пусто}"

read -rp "Куда писать (Enter — out/<маршрут>_<время>.txt): " TARGET
read -rp "Исключить IPv6? [Y/n]: " SKIP_V6

EXTRA=()
if [[ ! "${SKIP_V6:-y}" =~ ^[Nn]$ ]]; then
    EXTRA+=(--no-ipv6)
fi
if [[ -n "$TARGET" ]]; then
    EXTRA+=(--out "$TARGET")
fi

echo
warn "будет перебран весь IPv4 страны и записан в один текстовый файл;"
warn "Ctrl+C безопасен: файл и курсор останутся согласованными, а повторный"
warn "запуск продолжит с того же места (--restart начинает заново)"
read -rp "Продолжить? [y/N]: " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    info "отменено"
    exit 0
fi

info "python -m src.main $COUNTRY ${EXTRA[*]:-}"
exec "$VENV_PYTHON" -m src.main "$COUNTRY" "${EXTRA[@]}"
