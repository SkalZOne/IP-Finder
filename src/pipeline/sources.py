"""Источники discovery. Бесплатные, без ключей."""

from ipaddress import ip_address, ip_network, summarize_address_range

from .fetch import fetch_json


RIPESTAT = "https://stat.ripe.net/data"
CERTSPOTTER = "https://api.certspotter.com/v1/issuances"


def to_networks(raw) -> list:
    """'1.2.3.0/24' или '1.2.3.0-1.2.3.255' -> список сетей.

    Реестр отдаёт ресурсы в обеих формах, поэтому диапазонная ветка здесь
    не «на всякий случай».
    """
    raw = (raw or "").strip()
    if not raw:
        return []

    if "-" in raw:
        low, _, high = raw.partition("-")
        try:
            first, last = ip_address(low.strip()), ip_address(high.strip())
        except ValueError:
            return []
        # На разных версиях summarize_address_range бросает TypeError, не ValueError.
        if first.version != last.version:
            return []
        try:
            return list(summarize_address_range(first, last))
        except ValueError:
            return []

    try:
        return [ip_network(raw, strict=False)]
    except ValueError:
        return []


def country(code: str):
    """Префиксы и номера AS страны -> (networks, asns)."""
    code = code.strip().upper()
    if len(code) != 2 or not code.isalpha():
        raise ValueError(f"нужен код страны из двух букв, получено {code!r}")

    payload = fetch_json(f"{RIPESTAT}/country-resource-list/data.json", {"resource": code})
    resources = _data(payload, code).get("resources") or {}

    networks = []
    for family in ("ipv4", "ipv6"):
        for raw in resources.get(family) or []:
            networks += to_networks(raw)

    # Номера AS лежат в resources.asn, а не в data.asns: второе поле пустое.
    asns = [int(a) for a in resources.get("asn") or [] if str(a).isdigit()]
    return networks, asns


def asn(number: int) -> list:
    """Анонсированные префиксы автономной системы."""
    resource = f"AS{int(number)}"
    payload = fetch_json(f"{RIPESTAT}/announced-prefixes/data.json", {"resource": resource})

    networks = []
    for entry in _data(payload, resource).get("prefixes") or []:
        raw = entry.get("prefix") if isinstance(entry, dict) else entry
        networks += to_networks(raw)
    return networks


def ct_names(domain: str) -> list[str]:
    """Имена из сертификатов домена, включая поддомены.

    Без ключа certspotter даёт 10 запросов на окно, поэтому это точечный
    инструмент, а не массовый. crt.sh как альтернатива сейчас лежит.
    """
    domain = domain.strip().lower().rstrip(".")
    if not domain:
        raise ValueError("нужен домен")

    payload = fetch_json(
        CERTSPOTTER,
        {"domain": domain, "include_subdomains": "true", "expand": "dns_names"},
    )
    if not isinstance(payload, list):
        raise ValueError(f"certspotter вернул не список для {domain}")

    names = set()
    for issuance in payload:
        for raw in issuance.get("dns_names") or []:
            name = raw.strip().lower().rstrip(".")
            # Дикая карточка не резолвится, а чужие домены из SAN нам не нужны.
            if name and not name.startswith("*."):
                if name == domain or name.endswith("." + domain):
                    names.add(name)
    return sorted(names)


def _data(payload, what: str) -> dict:
    """RIPEstat кладёт ошибку в поле status при HTTP 200, а не в код ответа."""
    if not isinstance(payload, dict):
        raise ValueError(f"RIPEstat вернул не словарь для {what}")
    if payload.get("status") not in (None, "ok"):
        raise ValueError(f"RIPEstat status={payload['status']!r} для {what}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError(f"RIPEstat не вернул data для {what}")
    return data
