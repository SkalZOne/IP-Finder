#!/usr/bin/env python3
"""Discovery двумя маршрутами, результат — текстовый файл.

    python -m src.main LI                     страна -> префиксы -> IP
    python -m src.main DE --no-ipv6
    python -m src.main --ct example.org       домен -> CT -> имена -> DNS -> IP

Запускать из корня проекта и только как модуль: файл импортирует
`src.pipeline`, то есть ожидает в sys.path корень проекта.

Результат — один текстовый файл, строка на запись: в маршруте по стране это
адрес, в CT-маршруте — «адрес<TAB>имя». По умолчанию файл получает имя
out/<маршрут>_<дата-время>.txt; своё задаётся через --out, а с --append можно
дописывать всё в один и тот же файл.

Прогон по стране продолжается с последнего записанного адреса: `--restart`
начинает заново, `--no-save` не пишет ничего, только показывает на экране.
"""

from __future__ import annotations

import argparse
import sys

from src.pipeline import normalize, sources, store


PREVIEW_LIMIT = 200


def run_country(args) -> int:
    try:
        networks, asns = sources.country(args.country)
    except (ValueError, RuntimeError) as exc:
        print(f"источник не ответил: {exc}", file=sys.stderr)
        return 1

    if args.no_ipv6:
        networks = [n for n in networks if n.version == 4]

    # Сети реестра пересекаются между собой; слияние заменяет дедупликацию,
    # которую раньше делала база, и по памяти не стоит ничего.
    networks = normalize.merge(networks)

    code = args.country.strip().upper()
    cursor = f"country:{code}"
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
    if args.no_save:
        for _ in seen():
            pass
        saved = 0
    else:
        path = store.output_path("country", args.out)
        with store.Output(
            path,
            append=args.append,
            on_flush=lambda last: store.set_cursor(cursor, last),
        ) as out:
            for ip in seen():
                out.write(ip)
        saved = out.count

    v4 = sum(1 for n in networks if n.version == 4)
    available = sum(n.num_addresses for n in networks if n.version == 4)

    print(
        f"# {code}: сетей {len(networks)} (IPv4 {v4}, IPv6 {len(networks) - v4}), AS {len(asns)}",
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


def run_ct(args) -> int:
    domain = args.ct.strip().lower()
    try:
        names = sources.ct_names(domain)
    except (ValueError, RuntimeError) as exc:
        print(f"источник не ответил: {exc}", file=sys.stderr)
        return 1

    # Имя — то, что делает цель осмысленной: без него веб-сервер отвечает 403.
    # DNS идёт последовательно, поэтому список имён умеет обрезаться.
    rows = [
        (ip, name)
        for name in names[: args.max_addresses or None]
        for ip in normalize.resolve_name(name)
    ]

    path = None
    if args.no_save:
        saved = 0
    else:
        path = store.output_path("ct", args.out)
        with store.Output(path, append=args.append) as out:
            for ip, name in rows:
                out.write(f"{ip}\t{name}")
        saved = out.count

    print(
        f"# {domain}: имён из CT {len(names)}, разрешено имён "
        f"{min(len(names), args.max_addresses or len(names))}, адресов {len(rows)}",
        file=sys.stderr,
    )
    print(f"# записано {saved:,}", file=sys.stderr)
    if path is not None:
        print(f"# файл: {path}", file=sys.stderr)

    for ip, name in rows[: args.limit]:
        print(f"{ip}  {name}")
    if len(rows) > args.limit:
        print(f"# ...и ещё {len(rows) - args.limit:,} (см. --limit)", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("country", nargs="?", help="код страны из двух букв, например LI")
    parser.add_argument("--ct", metavar="ДОМЕН", help="раскрыть домен через CT-логи")
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
    parser.add_argument("--no-cache", action="store_true", help="не читать и не писать кэш ответов")
    args = parser.parse_args(argv)

    if not args.ct and not args.country:
        parser.error("нужен либо код страны, либо --ct ДОМЕН")

    store.CACHE_ENABLED = not args.no_cache
    return run_ct(args) if args.ct else run_country(args)


if __name__ == "__main__":
    raise SystemExit(main())
