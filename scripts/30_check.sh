#!/bin/bash
# ORDER: 30
# DESC: Проверить окружение, каталоги и доступность источников
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.bash"

PY="$(python_bin)"
info "python: $("$PY" --version 2>&1) ($PY)"
[[ -x "$VENV_PYTHON" ]] && note "venv: $VENV_DIR" || warn "venv не создан — scripts/10_install.sh"
echo

"$PY" - <<'PY'
import os
import sys

sys.path.insert(0, os.getcwd())

try:
    import requests
except ImportError as exc:
    print(f"зависимости: НЕТ ({exc}) — запустите scripts/10_install.sh")
    sys.exit(1)

print("зависимости: есть")

from src.pipeline import store

for title, path in (("результаты (out)", store.OUT_DIR), ("данные (data)", store.DATA_DIR)):
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        print(f"{title}: {path} — писать нельзя ({exc})")
        sys.exit(1)
    print(f"{title}: {path} — писать можно")

try:
    response = requests.get(
        "https://stat.ripe.net/data/country-resource-list/data.json",
        params={"resource": "LI"},
        timeout=15,
        headers={"User-Agent": "ip-finder/0.1"},
    )
    response.raise_for_status()
except requests.RequestException as exc:
    print(f"RIPEstat: недоступен ({exc}) — прогоны не пройдут")
    sys.exit(1)

print(f"RIPEstat: отвечает ({response.status_code}), источник доступен")
print("всё готово к запуску")
PY
