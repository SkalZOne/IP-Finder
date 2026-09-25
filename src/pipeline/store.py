"""Файловое хранилище: результат прогона, кэш ответов и курсоры.

Базы здесь нет намеренно. Результат — обычный текстовый файл, кэш и позиции
продолжения лежат рядом обычными файлами:

    out/<маршрут>_<дата-время>.txt   результат, одна строка на запись
    data/cache/<хеш>.json            ответы источников вместе со временем загрузки
    data/state/<имя>.cursor          последний записанный адрес

Каталоги можно переопределить через окружение (IPFINDER_DATA, IPFINDER_OUT)
или через .env в корне проекта.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# .env — необязательный: он всего лишь способ задать пути, не трогая код.
ENV_PATH = PROJECT_ROOT / ".env"
try:
    from dotenv import load_dotenv
except ImportError:  # без python-dotenv работаем на переменных окружения
    load_dotenv = None

if load_dotenv is not None and ENV_PATH.is_file():
    load_dotenv(ENV_PATH, override=False)

# Значения читаются при каждом обращении к модулю, поэтому тесты и скрипты
# могут подменить их на лету.
DATA_DIR = Path(os.getenv("IPFINDER_DATA") or PROJECT_ROOT / "data")
OUT_DIR = Path(os.getenv("IPFINDER_OUT") or PROJECT_ROOT / "out")

# --no-cache выключает кэш целиком: и чтение, и запись.
CACHE_ENABLED = True


def _cache_file(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    return DATA_DIR / "cache" / f"{digest}.json"


def cache_get(url: str, max_age: float | None) -> str | None:
    """Тело ответа, если запись есть и не старше max_age (None — без срока)."""
    if not CACHE_ENABLED:
        return None

    path = _cache_file(url)
    if not path.is_file():
        return None

    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = float(entry["fetched_at"])
        body = entry["body"]
    except (OSError, ValueError, KeyError, TypeError):
        return None  # битая запись — это промах, а не падение прогона

    if max_age is not None and time.time() - fetched_at > max_age:
        return None
    return body


def cache_put(url: str, body: str) -> None:
    """Пишет ответ источника. Через временный файл: обрыв не оставит половину JSON."""
    if not CACHE_ENABLED:
        return

    path = _cache_file(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"url": url, "fetched_at": time.time(), "body": body}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _state_file(name: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    return DATA_DIR / "state" / f"{safe}.cursor"


def get_cursor(name: str) -> str | None:
    path = _state_file(name)
    if not path.is_file():
        return None
    value = path.read_text(encoding="utf-8").strip()
    return value or None


def set_cursor(name: str, value: str) -> None:
    path = _state_file(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(value + "\n", encoding="utf-8")
    tmp.replace(path)


def output_path(route: str, explicit: str | None = None) -> Path:
    """Куда писать результат: --out, либо out/<маршрут>_<дата-время>.txt."""
    if explicit:
        return Path(explicit).expanduser()
    return OUT_DIR / f"{route}_{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.txt"


class Output:
    """Запись результата потоком: одна строка на запись, без накопления в памяти.

    flush_every нужен не столько файлу (его допишет close), сколько on_flush:
    двигать курсор безопасно только на границе сброшенного буфера, иначе он
    укажет за пределы записанного.
    """

    def __init__(
        self,
        path: Path,
        append: bool = False,
        flush_every: int = 5000,
        on_flush=None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.count = 0
        self._last_line: str | None = None
        self._on_flush = on_flush
        self._flush_every = max(1, flush_every)
        self._handle = self.path.open("a" if append else "w", encoding="utf-8", newline="\n")

    def write(self, line: str) -> None:
        self._handle.write(line + "\n")
        self._last_line = line
        self.count += 1
        if self.count % self._flush_every == 0:
            self._flush()

    def _flush(self) -> None:
        self._handle.flush()
        os.fsync(self._handle.fileno())
        if self._on_flush and self._last_line is not None:
            self._on_flush(self._last_line)

    def close(self) -> None:
        if self._handle.closed:
            return
        self._flush()
        self._handle.close()

    def __enter__(self) -> "Output":
        return self

    def __exit__(self, *exc) -> None:
        # Закрываемся и при Ctrl+C: файл и курсор остаются согласованными,
        # поэтому прерванный прогон продолжается с того же места.
        self.close()
