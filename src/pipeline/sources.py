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
    if not isinstance(raw, str):
        return []
    raw = raw.strip()
    if not raw:
        return []

    if "-" in raw:
        low, _, high = raw.partition("-")
        try:
            first, last = ip_address(low.strip()), ip_address(high.strip())
        except (TypeError, ValueError):
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
    if len(code) != 2 or not code.isascii() or not code.isalpha():
        raise ValueError(f"нужен код страны из двух букв, получено {code!r}")

    payload = fetch_json(
        f"{RIPESTAT}/country-resource-list/data.json",
        {"resource": code},
        validate=lambda value: _country_resources(value, code),
    )
    resources = _country_resources(payload, code)

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
    payload = fetch_json(
        f"{RIPESTAT}/announced-prefixes/data.json",
        {"resource": resource},
        validate=lambda value: _asn_prefixes(value, resource),
    )

    networks = []
    for entry in _asn_prefixes(payload, resource):
        raw = entry.get("prefix") if isinstance(entry, dict) else entry
        networks += to_networks(raw)
    return networks


def ct_names(domain: str, max_pages: int = 1) -> list[str]:
    """Имена из сертификатов домена, включая поддомены и до max_pages страниц."""
    domain = domain.strip().lower().rstrip(".")
    try:
        domain = domain.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("некорректный домен") from exc
    labels = domain.split(".")
    if (
        not 1 <= max_pages <= 10
        or not domain
        or len(domain) > 253
        or any(
            not label
            or len(label) > 63
            or label[0] == "-"
            or label[-1] == "-"
            or not all(c.isascii() and (c.isalnum() or c == "-") for c in label)
            for label in labels
        )
    ):
        raise ValueError("некорректный домен или --ct-pages")

    params = {"domain": domain, "include_subdomains": "true", "expand": "dns_names"}
    names = set()
    after = None
    for page_index in range(max_pages):
        if after is not None:
            params["after"] = after
        payload = fetch_json(
            CERTSPOTTER,
            params.copy(),
            validate=lambda value: _ct_page(value, domain),
        )
        _ct_page(payload, domain)
        if not payload:
            break
        for issuance in payload:
            for raw in issuance.get("dns_names") or []:
                if not isinstance(raw, str):
                    continue
                name = raw.strip().lower().rstrip(".")
                # Дикая карточка не резолвится, а чужие домены из SAN нам не нужны.
                if name and not name.startswith("*."):
                    if name == domain or name.endswith("." + domain):
                        names.add(name)
        new_after = payload[-1].get("id")
        if page_index < max_pages - 1 and new_after is None:
            raise ValueError("certspotter не вернул id для следующей страницы")
        if new_after is not None and new_after == after:
            raise ValueError("certspotter повторил страницу")
        after = new_after
    return sorted(names)


def _ct_page(payload, domain: str) -> None:
    if not isinstance(payload, list):
        raise ValueError(f"certspotter вернул не список для {domain}")
    if not all(isinstance(entry, dict) for entry in payload):
        raise ValueError("certspotter вернул некорректную запись")
    if not all(
        entry.get("dns_names") is None or isinstance(entry.get("dns_names"), list)
        for entry in payload
    ):
        raise ValueError("certspotter вернул некорректный список имён")


def _country_resources(payload, code: str) -> dict:
    resources = _data(payload, code).get("resources")
    if not isinstance(resources, dict) or any(
        resources.get(key) is not None and not isinstance(resources.get(key), list)
        for key in ("ipv4", "ipv6", "asn")
    ):
        raise ValueError(f"RIPEstat вернул некорректные ресурсы для {code}")
    return resources


def _asn_prefixes(payload, resource: str) -> list:
    prefixes = _data(payload, resource).get("prefixes")
    if not isinstance(prefixes, list):
        raise ValueError(f"RIPEstat вернул некорректные префиксы для {resource}")
    return prefixes


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
