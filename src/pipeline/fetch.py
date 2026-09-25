"""HTTP с файловым кэшем, ретраями и приоритетом IPv4."""

import json
import socket
import time
from urllib.parse import urlencode

import requests
from urllib3.util import connection

from . import store


# В этом окружении DNS отдаёт AAAA-записи, а IPv6 не маршрутизируется:
# запросы висят до таймаута. Одна строка лечит всё.
connection.allowed_gai_family = lambda: socket.AF_INET

RETRY_STATUS = {429, 500, 502, 503, 504}
USER_AGENT = "ip-finder/0.1"
MAX_AGE = 7 * 24 * 3600


def fetch_text(url, params=None, *, max_age=MAX_AGE, tries=4, timeout=30.0) -> str:
    """GET с кэшем. Кэш проверяется до сети, ошибки в него не пишутся."""
    key = url + "?" + urlencode(sorted((params or {}).items()))

    cached = store.cache_get(key, max_age)
    if cached is not None:
        return cached

    error = None
    for attempt in range(tries):
        try:
            response = requests.get(
                url, params=params, timeout=timeout, headers={"User-Agent": USER_AGENT}
            )
        except requests.RequestException as exc:
            error = exc
        else:
            if response.status_code not in RETRY_STATUS:
                response.raise_for_status()
                store.cache_put(key, response.text)
                return response.text
            error = f"HTTP {response.status_code}"

        if attempt < tries - 1:
            time.sleep(min(0.5 * 2**attempt, 8.0))

    raise RuntimeError(f"{key}: не удалось за {tries} попыток ({error})")


def fetch_json(url, params=None, **kwargs):
    return json.loads(fetch_text(url, params, **kwargs))
