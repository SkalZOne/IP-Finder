"""Попадания источников -> поток IP-адресов."""

import itertools
import socket
from ipaddress import ip_address


PER_PREFIX = 32

# IPv6 не разворачивается целиком никогда: у LI в нём порядка 10^30 адресов.
MAX_IPV6_PER_PREFIX = 32


def _limit(network, per_prefix: int) -> int:
    """0 значит «все» и допустимо только для IPv4."""
    if network.version == 6 and per_prefix <= 0:
        return MAX_IPV6_PER_PREFIX
    return per_prefix


def iter_prefix_ips(network, per_prefix: int = 0):
    stream = network.hosts()
    limit = _limit(network, per_prefix)
    if limit > 0:
        stream = itertools.islice(stream, limit)
    for ip in stream:
        yield str(ip)


def merge(networks):
    """Убирает сети, целиком вложенные в другие: один адрес не должен выйти дважды.

    Заменяет дедупликацию, которую раньше делал первичный ключ базы, и по памяти
    не стоит ничего. Соседние, но не вложенные сети остаются раздельными:
    `--per-prefix` считается от каждой сети, и склеивать их — менять смысл флага.
    Два CIDR либо не пересекаются, либо один вложен в другой, поэтому проверки
    вложенности достаточно. Порядок (версия, начало сети) сохраняется — на него
    опирается iter_from.
    """
    kept = []
    for network in sorted(
        networks, key=lambda n: (n.version, int(n.network_address), n.prefixlen)
    ):
        if kept and kept[-1].version == network.version and network.subnet_of(kept[-1]):
            continue
        kept.append(network)
    return kept


def iter_from(networks, cursor: str | None = None, per_prefix: int = 0):
    """Адреса сетей по возрастанию, начиная со следующего после `cursor`.

    `networks` должны быть отсортированы: IPv4, затем IPv6, внутри версии по
    возрастанию. При таком порядке сеть целиком позади курсора отсекается
    сравнением, без единого обращения к адресу.
    """
    start = ip_address(cursor) if cursor else None
    start_order = (start.version, int(start)) if start else None

    for network in networks:
        if start_order and (network.version, int(network.broadcast_address)) <= start_order:
            continue

        hosts = network.hosts()
        first = next(hosts, None)
        if first is None:
            continue

        stream = itertools.chain([first], hosts)
        skip = 0

        if start is not None and start in network:
            skip = max(0, int(start) + 1 - int(first))
            if skip:
                stream = itertools.islice(stream, skip, None)

        limit = _limit(network, per_prefix)
        if limit > 0:
            limit -= skip  # выборка считается от начала сети
            if limit <= 0:
                continue
            stream = itertools.islice(stream, limit)

        for ip in stream:
            yield str(ip)


def take(ips, limit: int | None):
    return ips if limit is None else itertools.islice(ips, limit)


def iter_ips(hits, per_prefix: int = 0):
    for hit in hits:
        if "prefix" in hit:
            yield from iter_prefix_ips(hit["prefix"], per_prefix)
        elif "name" in hit:
            yield from resolve_name(hit["name"])
        elif "ip" in hit:
            yield str(hit["ip"])


def resolve_name(name: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(name, None, socket.AF_INET)
    except socket.gaierror:
        return []
    return sorted({info[4][0] for info in infos}, key=_sort_key)


def _sort_key(text: str):
    addr = ip_address(text)
    return (addr.version, int(addr))
