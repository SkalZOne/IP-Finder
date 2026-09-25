#!/usr/bin/env python3
"""Поиск IP по стране, AS или домену; результат — текстовый файл.

    python -m src.main LI                     страна -> префиксы -> IP
    python -m src.main DE --no-ipv6
    python -m src.main --asn AS3333            ASN -> анонсированные префиксы -> IP
    python -m src.main --ct example.org       домен -> CT -> имена -> DNS -> IP

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

import argparse
import hashlib
import sys
from pathlib import Path

from src.pipeline import normalize, sources, store


PREVIEW_LIMIT = 200


def run_networks(args, *, kind: str, resource: str) -> int:
    try:
        if kind == "country":
            networks, asns = sources.country(resource)
        else:
            networks, asns = sources.asn(int(resource[2:])), [int(resource[2:])]
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"источник не ответил: {exc}", file=sys.stderr)
        return 1

    if args.no_ipv6:
        networks = [n for n in networks if n.version == 4]

    # Сети реестра пересекаются между собой; слияние заменяет дедупликацию,
    # которую раньше делала база, и по памяти не стоит ничего.
    networks = normalize.merge(networks)

    label = resource.upper()
    # Курсор привязан к настройкам и снимку сетей: изменение источника
    # не должно незаметно пропускать новые префиксы.
    digest = hashlib.blake2s(
        "\n".join(str(network) for network in networks).encode(), digest_size=8
    ).hexdigest()
    cursor = f"{kind}:{label}:p{args.per_prefix}:v{'4' if args.no_ipv6 else '46'}:{digest}"
    resume = None if (args.restart or args.no_save) else store.get_cursor(cursor)

    stream = normalize.take(
        normalize.iter_from(networks, resume, args.per_prefix), args.max_addresses or None
    )

    preview: list[str] = []
    total = 0

    def seen():
        nonlocal total
        for ip in stream:
            total += 1
            if len(preview) < args.limit:
                preview.append(ip)
            yield ip

    path = None
    try:
        if args.no_save:
            for _ in seen():
                pass
            saved = 0
        else:
            path = store.output_path(kind, args.out)
            check_output(path, args)
            with store.Output(
                path,
                append=args.append,
                on_flush=lambda last: store.set_cursor(cursor, last),
            ) as out:
                for ip in seen():
                    out.write(ip)
            saved = out.count
    except (OSError, ValueError) as exc:
        print(f"ошибка записи: {exc}", file=sys.stderr)
        return 1

    v4 = sum(1 for n in networks if n.version == 4)
    available = sum(n.num_addresses for n in networks if n.version == 4)

    print(
        f"# {label}: сетей {len(networks)} (IPv4 {v4}, IPv6 {len(networks) - v4}), AS {len(asns)}",
        file=sys.stderr,
    )
    print(f"# в них IPv4-адресов {available:,}", file=sys.stderr)
    if resume:
        print(f"# продолжаем с {resume}", file=sys.stderr)
    print(
        f"# отдано {total:,} (per-prefix {args.per_prefix or 'все'}), записано {saved:,}",
        file=sys.stderr,
    )
    if path is not None:
        print(f"# файл: {path}", file=sys.stderr)

    for ip in preview:
        print(ip)
    if total > len(preview):
        print(f"# ...и ещё {total - len(preview):,} (см. --limit)", file=sys.stderr)
    return 0


def check_output(path: Path, args) -> None:
    if path.exists() and not (args.append or args.force):
        raise ValueError(f"файл {path} уже существует; используйте --append или --force")


def run_ct(args) -> int:
    domain = args.ct.strip().lower()
    try:
        names = sources.ct_names(domain, max_pages=args.ct_pages)
    except (ValueError, RuntimeError) as exc:
        print(f"источник не ответил: {exc}", file=sys.stderr)
        return 1

    selected = names[: args.max_addresses or None]
    rows = normalize.iter_resolved(
        selected, workers=args.workers, include_ipv6=args.include_ipv6
    )

    path = None
    preview: list[tuple[str, str]] = []
    total = 0
    try:
        if args.no_save:
            saved = 0
            for ip, name in rows:
                total += 1
                if len(preview) < args.limit:
                    preview.append((ip, name))
        else:
            path = store.output_path("ct", args.out)
            check_output(path, args)
            with store.Output(path, append=args.append) as out:
                for ip, name in rows:
                    total += 1
                    if len(preview) < args.limit:
                        preview.append((ip, name))
                    out.write(f"{ip}\t{name}")
            saved = out.count
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ошибка записи или DNS: {exc}", file=sys.stderr)
        return 1

    print(
        f"# {domain}: имён из CT {len(names)}, разрешено имён "
        f"{len(selected)}, адресов {total}",
        file=sys.stderr,
    )
    print(f"# записано {saved:,}", file=sys.stderr)
    if path is not None:
        print(f"# файл: {path}", file=sys.stderr)

    for ip, name in preview:
        print(f"{ip}  {name}")
    if total > len(preview):
        print(f"# ...и ещё {total - len(preview):,} (см. --limit)", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("country", nargs="?", help="код страны из двух букв, например LI")
    parser.add_argument("--ct", metavar="ДОМЕН", help="раскрыть домен через CT-логи")
    parser.add_argument("--asn", metavar="AS123", help="анонсированные сети автономной системы")
    parser.add_argument(
        "--per-prefix", type=int, default=0, help="адресов из каждой сети; 0 = все IPv4"
    )
    parser.add_argument(
        "--max-addresses",
        type=int,
        default=0,
        help="остановиться после N адресов; в CT-маршруте — после N имён",
    )
    parser.add_argument("--no-ipv6", action="store_true", help="не включать IPv6")
    parser.add_argument("--restart", action="store_true", help="начать заново, забыв курсор")
    parser.add_argument(
        "--limit", type=int, default=PREVIEW_LIMIT, help="сколько строк напечатать на экран"
    )
    parser.add_argument("--no-save", action="store_true", help="файл не писать, только показать")
    parser.add_argument(
        "--out",
        metavar="ФАЙЛ",
        help="куда писать результат; по умолчанию out/<маршрут>_<дата-время>.txt",
    )
    parser.add_argument("--append", action="store_true", help="дописывать в файл, а не заменять")
    parser.add_argument("--force", action="store_true", help="разрешить замену существующего --out")
    parser.add_argument("--workers", type=int, default=8, help="параллельных DNS-запросов для CT (1–32)")
    parser.add_argument("--ct-pages", type=int, default=1, help="страниц Cert Spotter для CT (1–10)")
    parser.add_argument("--include-ipv6", action="store_true", help="искать также AAAA-записи в CT-режиме")
    parser.add_argument("--no-cache", action="store_true", help="не читать и не писать кэш ответов")
    args = parser.parse_args(argv)

    if sum(bool(value) for value in (args.country, args.ct, args.asn)) != 1:
        parser.error("укажите ровно одну цель: код страны, --ct ДОМЕН или --asn AS123")
    if args.country and (
        len(args.country) != 2 or not args.country.isascii() or not args.country.isalpha()
    ):
        parser.error("код страны должен состоять из двух латинских букв")
    if args.asn:
        number = args.asn.upper().removeprefix("AS")
        if not number.isascii() or not number.isdecimal() or int(number) < 1:
            parser.error("ASN должен иметь вид AS123 или 123")
        args.asn = f"AS{int(number)}"
    if args.per_prefix < 0 or args.max_addresses < 0 or args.limit < 0:
        parser.error("числовые лимиты не могут быть отрицательными")
    if not 1 <= args.workers <= 32:
        parser.error("--workers должен быть в диапазоне 1–32")
    if not 1 <= args.ct_pages <= 10:
        parser.error("--ct-pages должен быть в диапазоне 1–10")
    if args.ct and (args.per_prefix or args.no_ipv6 or args.restart):
        parser.error("--per-prefix, --no-ipv6 и --restart применимы только к сетям")
    if not args.ct and (args.workers != 8 or args.ct_pages != 1 or args.include_ipv6):
        parser.error("--workers, --ct-pages и --include-ipv6 применимы только к CT-режиму")
    if args.no_save and (args.out or args.append or args.force):
        parser.error("--no-save нельзя сочетать с --out, --append или --force")
    if args.append and (not args.out or args.force):
        parser.error("--append требует --out и не сочетается с --force")
    if args.force and not args.out:
        parser.error("--force требует --out")

    store.CACHE_ENABLED = not args.no_cache
    if args.ct:
        return run_ct(args)
    if args.asn:
        return run_networks(args, kind="asn", resource=args.asn)
    return run_networks(args, kind="country", resource=args.country)


if __name__ == "__main__":
    raise SystemExit(main())
