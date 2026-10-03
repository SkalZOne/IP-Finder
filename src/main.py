#!/usr/bin/env python3
"""IP-адреса из открытых источников: HTTP-сервис и CLI.

HTTP-сервис (`uvicorn src.main:app`): POST /rep с телом {"country": "DE"}
возвращает IPv4-адреса страны в JSON; без поля count отдаются все адреса
(тело собирается потоково, поэтому размер ответа память не ограничивает).

CLI: страна, AS, домен или Shodan; результат — текстовый файл.

    python -m src.main LI                     страна -> префиксы -> IP
    python -m src.main DE --per-prefix 10
    python -m src.main --asn AS3333            ASN -> анонсированные префиксы -> IP
    python -m src.main --ct example.org       домен -> CT -> имена -> DNS -> IP
    python -m src.main --shodan 'nginx country:DE'

Запускать из корня проекта и только как модуль: файл импортирует
`src.pipeline`, то есть ожидает в sys.path корень проекта.

Результат — один текстовый файл, строка на запись: в сетевых маршрутах это
адрес, в CT-маршруте — «адрес<TAB>имя». По умолчанию файл получает имя
out/<маршрут>_<дата-время>.txt; своё задаётся через --out, а с --append можно
дописывать всё в один и тот же файл.

Прогон по стране или ASN продолжается с последнего записанного адреса: `--restart`
начинает заново, `--no-save` не пишет ничего, только показывает на экране.
"""

from __future__ import annotations

import itertools
import json

from src.pipeline import normalize, sources

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field


class REPRequest(BaseModel):
    # Лишние поля — ошибка: опечатка в имени лимита не должна молча означать
    # «отдай все адреса страны».
    model_config = ConfigDict(extra="forbid")

    country: str = Field(
        ...,
        min_length=2,
        max_length=2,
        pattern=r"^[A-Za-z]{2}$",
        description="Код страны из двух латинских букв, например DE",
    )
    count: int | None = Field(
        None,
        ge=1,
        description=(
            "Сколько IPv4-адресов вернуть. Поле не задано — возвращаются все "
            "адреса страны; truncated=true означает, что список обрезан"
        ),
    )

class REPResponse(BaseModel):
    country: str
    count: int
    truncated: bool
    addresses: list[str]

app = FastAPI()


@app.post("/rep", response_model=REPResponse)
def rep(request: REPRequest) -> StreamingResponse:
    """IPv4-адреса страны: до count штук, а без count — все."""
    # Синхронный обработчик намеренно: sources.country ходит в RIPEstat через
    # requests, и в async-функции этот вызов заблокировал бы цикл событий.
    # FastAPI выполняет def-обработчики в пуле потоков.
    country = request.country.upper()
    try:
        networks, _ = sources.country(country)
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=502, detail=f"источник не ответил: {exc}") from exc

    # Вложенные сети дали бы повторы, поэтому merge оставляет только внешние.
    ipv4 = normalize.merge([n for n in networks if n.version == 4])

    # Точный размер известен заранее: пересечений после merge нет.
    total = sum(_addresses_in(network) for network in ipv4)
    count = total if request.count is None else min(request.count, total)
    truncated = request.count is not None and total > request.count

    def body():
        """JSON собирается порциями: адресов в стране могут быть десятки
        миллионов, и готовый список в памяти не поместился бы."""
        yield (
            f'{{"country":{json.dumps(country)},"count":{count},'
            f'"truncated":{"true" if truncated else "false"},"addresses":['
        )
        stream = normalize.iter_from(ipv4, per_prefix=0)
        if count < total:
            stream = itertools.islice(stream, count)
        batch: list[str] = []
        separator = ""
        for ip in stream:
            batch.append(f'"{ip}"')
            if len(batch) >= 4096:
                yield separator + ",".join(batch)
                separator = ","
                batch.clear()
        yield separator + ",".join(batch) + "]}"

    return StreamingResponse(body(), media_type="application/json")


def _addresses_in(network) -> int:
    """Сколько адресов iter_from отдаст для одной сети (только IPv4)."""
    if network.prefixlen < 31:  # iter_from пропускает адрес сети и broadcast
        return network.num_addresses - 2
    return network.num_addresses