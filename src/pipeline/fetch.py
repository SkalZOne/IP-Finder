"""HTTP с файловым кэшем, ретраями и приоритетом IPv4."""

import hashlib
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


def fetch_text(
    url, params=None, *, max_age=MAX_AGE, tries=4, timeout=30.0,
    validate=None, secret_params=(),
) -> str:
    """GET с кэшем; secret_params хешируются в ключе кэша и тексте ошибок."""
    safe_params = dict(params or {})
    for name in secret_params:
        if name in safe_params:
            digest = hashlib.sha256(str(safe_params[name]).encode()).hexdigest()
            safe_params[name] = f"sha256:{digest}"
    key = url + "?" + urlencode(sorted(safe_params.items()))

    cached = store.cache_get(key, max_age)
    if cached is not None:
        try:
            if validate:
                validate(cached)
            return cached
        except ValueError:
            pass  # испорченный кэш обновится из источника

    error = None
    for attempt in range(tries):
        response = None
        try:
            response = requests.get(
                url, params=params, timeout=timeout, headers={"User-Agent": USER_AGENT}
            )
        except requests.RequestException as exc:
            # Исключения requests могут содержать URL со значением API-ключа.
            error = type(exc).__name__
        else:
            if response.status_code not in RETRY_STATUS:
                try:
                    response.raise_for_status()
                except requests.HTTPError:
                    raise RuntimeError(f"{key}: HTTP {response.status_code}") from None
                try:
                    if validate:
                        validate(response.text)
                except ValueError as exc:
                    error = f"некорректный ответ: {exc}"
                else:
                    store.cache_put(key, response.text)
                    return response.text
            else:
                error = f"HTTP {response.status_code}"

        if attempt < tries - 1:
            delay = min(0.5 * 2**attempt, 8.0)
            if response is not None and response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "")
                if retry_after.isdecimal():
                    delay = min(max(delay, int(retry_after)), 30.0)
            time.sleep(delay)

    raise RuntimeError(f"{key}: не удалось за {tries} попыток ({error})")


def fetch_json(url, params=None, *, validate=None, **kwargs):
    def decode(body):
        payload = json.loads(body)
        if validate:
            validate(payload)
        return payload

    return decode(fetch_text(url, params, validate=decode, **kwargs))
