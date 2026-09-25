# Общая часть скриптов IP-finder: пути, цвета и проверки окружения.
# Расширение .bash не позволяет init.sh принять библиотеку за команду меню.

set -euo pipefail

COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$COMMON_DIR/../.." && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"

GREEN=$'\033[1;32m'
YELLOW=$'\033[1;33m'
RED=$'\033[1;31m'
DIM=$'\033[2m'
RESET=$'\033[0m'

info() { printf '%s==>%s %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '%sвнимание:%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
fail() { printf '%sошибка:%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }
note() { printf '%s%s%s\n' "$DIM" "$*" "$RESET"; }

# Python из venv, если он уже создан, иначе системный.
python_bin() {
    if [[ -x "$VENV_PYTHON" ]]; then
        printf '%s' "$VENV_PYTHON"
    else
        printf '%s' "${PYTHON_BIN:-python3}"
    fi
}

require_python() {
    command -v "$(python_bin)" >/dev/null 2>&1 || fail "не найден python3 в PATH"
}

require_venv() {
    [[ -x "$VENV_PYTHON" ]] || fail "нет venv ($VENV_DIR) — сначала запустите scripts/10_install.sh"
}

# Без зависимостей скрипты падают с невнятным ImportError, поэтому проверяем заранее.
require_deps() {
    require_venv
    "$VENV_PYTHON" -c "import requests" >/dev/null 2>&1 \
        || fail "в venv нет зависимостей — запустите scripts/10_install.sh"
}

# Все команды выполняются из корня проекта: иначе `python -m src.main` не находит пакет.
require_project_root() {
    [[ -f "$PROJECT_ROOT/src/main.py" ]] || fail "не найден $PROJECT_ROOT/src/main.py"
    cd "$PROJECT_ROOT"
}

require_project_root
