"""Тесты пайплайна. Один файл, потому что кода немного.

Каждый тест здесь появился не ради покрытия, а после конкретной ошибки или
конкретного риска: разбор диапазонной формы, проверка status при HTTP 200,
слияние пересекающихся сетей вместо дедупликации базой, память на
стомиллионном диапазоне, согласованность курсора с уже записанным файлом.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from src import main
from src.pipeline import fetch, normalize, sources, store


class ToNetworksTests(unittest.TestCase):
    def test_cidr(self) -> None:
        self.assertEqual(sources.to_networks("8.8.8.0/24"), [ipaddress.ip_network("8.8.8.0/24")])

    def test_host_bits_are_masked(self) -> None:
        self.assertEqual(sources.to_networks("8.8.8.7/24"), [ipaddress.ip_network("8.8.8.0/24")])

    def test_range_notation(self) -> None:
        """Регрессия: диапазонная форма реестра молча терялась.

        Проверяется покрытие, а не конкретная декомпозиция: важны точные
        границы и отсутствие дыр.
        """
        nets = sources.to_networks("194.147.196.0-194.147.207.255")

        self.assertTrue(nets)
        self.assertEqual(sum(n.num_addresses for n in nets), 12 * 256)
        self.assertEqual(int(nets[0].network_address), int(ipaddress.ip_address("194.147.196.0")))
        self.assertEqual(int(nets[-1].broadcast_address), int(ipaddress.ip_address("194.147.207.255")))
        for left, right in zip(nets, nets[1:]):
            self.assertEqual(int(left.broadcast_address) + 1, int(right.network_address))

    def test_single_address_range(self) -> None:
        self.assertEqual(
            sources.to_networks("10.0.0.1-10.0.0.1"), [ipaddress.ip_network("10.0.0.1/32")]
        )

    def test_garbage_is_empty(self) -> None:
        for bad in ("", "   ", "не-префикс", "8.8.8.0/33", "1.2.3", "10.0.0.5-10.0.0.1", "8.8.8.0-::1", "8.8.8.0-"):
            self.assertEqual(sources.to_networks(bad), [], msg=bad)


class SourcePayloadTests(unittest.TestCase):
    def test_error_status_at_http_200_raises(self) -> None:
        """RIPEstat кладёт ошибку в поле, а не в код ответа."""
        with self.assertRaises(ValueError) as ctx:
            sources._data({"status": "error", "messages": ["bad"]}, "AS1")
        self.assertIn("error", str(ctx.exception))

    def test_missing_data_raises(self) -> None:
        with self.assertRaises(ValueError):
            sources._data({"status": "ok"}, "AS1")

    def test_non_dict_raises(self) -> None:
        with self.assertRaises(ValueError):
            sources._data(["не словарь"], "AS1")

    def test_ok_passes_through(self) -> None:
        self.assertEqual(sources._data({"status": "ok", "data": {"x": 1}}, "AS1"), {"x": 1})

    def test_malformed_country_resources_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            sources._country_resources({"status": "ok", "data": {"resources": []}}, "LI")

    def test_malformed_asn_prefixes_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            sources._asn_prefixes({"status": "ok", "data": {"prefixes": {}}}, "AS1")


class CtNamesTests(unittest.TestCase):
    """Разбор ответа certspotter. Форма снята с живого API."""

    PAYLOAD = [
        {"id": 1, "dns_names": ["www.example.org", "example.org"], "revoked": False},
        {"id": 2, "dns_names": ["*.example.org", "MAIL.Example.org."], "revoked": False},
        {"id": 3, "dns_names": ["other.invalid", "www.example.org"], "revoked": True},
    ]

    def names(self, payload, domain="example.org"):
        with mock.patch("src.pipeline.sources.fetch_json", return_value=payload):
            return sources.ct_names(domain)

    def test_collects_unique_sorted_lowercase(self) -> None:
        self.assertEqual(
            self.names(self.PAYLOAD), ["example.org", "mail.example.org", "www.example.org"]
        )

    def test_wildcards_are_skipped(self) -> None:
        self.assertNotIn("*.example.org", self.names(self.PAYLOAD))

    def test_foreign_san_names_are_dropped(self) -> None:
        """В SAN сертификата попадают чужие домены — они не часть этого домена."""
        self.assertNotIn("other.invalid", self.names(self.PAYLOAD))

    def test_revoked_certificate_still_proves_the_name(self) -> None:
        payload = [{"dns_names": ["old.example.org"], "revoked": True}]
        self.assertEqual(self.names(payload), ["old.example.org"])

    def test_domain_is_normalized_for_the_query(self) -> None:
        seen = {}

        def fake(url, params=None, **kwargs):
            seen.update(params)
            return []

        with mock.patch("src.pipeline.sources.fetch_json", side_effect=fake):
            sources.ct_names("  Example.ORG.  ")

        self.assertEqual(seen["domain"], "example.org")
        self.assertEqual(seen["include_subdomains"], "true")

    def test_empty_domain_rejected(self) -> None:
        for bad in ("", "   ", "."):
            with self.assertRaises(ValueError, msg=bad):
                sources.ct_names(bad)

    def test_non_list_payload_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.names({"error": "rate limited"})

    def test_malformed_dns_names_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.names([{"id": "1", "dns_names": "bad.example.org"}])

    def test_reads_next_page_using_last_id(self) -> None:
        pages = [
            [{"id": "11", "dns_names": ["a.example.org"]}],
            [{"id": "12", "dns_names": ["b.example.org"]}],
            [],
        ]
        with mock.patch("src.pipeline.sources.fetch_json", side_effect=pages) as get:
            names = sources.ct_names("example.org", max_pages=3)
        self.assertEqual(names, ["a.example.org", "b.example.org"])
        self.assertEqual(get.call_args_list[1].args[1]["after"], "11")
        self.assertEqual(get.call_args_list[2].args[1]["after"], "12")

    def test_invalid_domain_is_rejected_before_request(self) -> None:
        with mock.patch("src.pipeline.sources.fetch_json") as get:
            with self.assertRaises(ValueError):
                sources.ct_names("bad..example.org")
        get.assert_not_called()


class NormalizeTests(unittest.TestCase):
    def ips(self, hits, **kwargs):
        return list(normalize.iter_ips(hits, **kwargs))

    def net(self, cidr):
        return {"prefix": ipaddress.ip_network(cidr)}

    def test_stream_is_a_generator_not_a_list(self) -> None:
        """Структурная проверка ленивости: список пришлось бы материализовать."""
        self.assertIsInstance(normalize.iter_ips([self.net("10.0.0.0/24")]), types.GeneratorType)

    def test_per_prefix_limit(self) -> None:
        self.assertEqual(
            self.ips([self.net("10.0.0.0/16")], per_prefix=3),
            ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
        )

    def test_per_prefix_zero_means_everything(self) -> None:
        ips = self.ips([self.net("10.0.0.0/24")], per_prefix=0)
        self.assertEqual(len(ips), 254)
        self.assertEqual(ips[0], "10.0.0.1")
        self.assertEqual(ips[-1], "10.0.0.254")

    def test_network_address_is_not_taken(self) -> None:
        """Сетевой адрес хостам не назначается — он никогда не ответит."""
        self.assertNotIn("10.0.0.0", self.ips([self.net("10.0.0.0/24")]))

    def test_slash_31_uses_both_addresses(self) -> None:
        self.assertEqual(self.ips([self.net("10.0.0.0/31")]), ["10.0.0.0", "10.0.0.1"])

    def test_slash_32(self) -> None:
        self.assertEqual(self.ips([self.net("10.0.0.7/32")]), ["10.0.0.7"])

    def test_huge_network_is_not_materialized(self) -> None:
        """Главная защита от OOM: из /8 (16.7 млн адресов) берём три.

        Если бы поток собирался в список, этот тест не завершился бы
        за разумное время и съел бы гигабайт памяти.
        """
        big = normalize.iter_ips([self.net("10.0.0.0/8")], per_prefix=0)
        self.assertEqual(list(normalize.take(big, 3)), ["10.0.0.1", "10.0.0.2", "10.0.0.3"])

    def test_take_without_limit_runs_to_end(self) -> None:
        stream = normalize.iter_ips([self.net("10.0.0.0/30")])
        self.assertEqual(list(normalize.take(stream, None)), ["10.0.0.1", "10.0.0.2"])

    def test_ipv6_is_never_fully_expanded(self) -> None:
        """Регрессия: `--per-prefix 0` на IPv6 висел вечно.

        У LI в IPv6 семь на десять в тридцатой адресов. Без жёсткого предела
        первый же прогон не завершился бы — что и произошло на 300 секундах.
        """
        huge = [{"prefix": ipaddress.ip_network("2001:db8::/32")}]
        ips = self.ips(huge, per_prefix=0)

        self.assertEqual(len(ips), normalize.MAX_IPV6_PER_PREFIX)
        self.assertTrue(all(ip.startswith("2001:db8:") for ip in ips), ips)

    def test_ipv6_explicit_limit_is_respected(self) -> None:
        huge = [{"prefix": ipaddress.ip_network("2001:db8::/32")}]
        self.assertEqual(len(self.ips(huge, per_prefix=5)), 5)

    def test_ipv4_zero_still_means_everything(self) -> None:
        """Предел введён только для IPv6 — IPv4 не должен пострадать."""
        self.assertEqual(len(self.ips([self.net("10.0.0.0/24")], per_prefix=0)), 254)

    def test_duplicates_are_left_to_the_database(self) -> None:
        """Поток не дедуплицирует: set из 126 млн строк и есть тот самый OOM."""
        self.assertEqual(self.ips([{"ip": "8.8.8.8"}, {"ip": "8.8.8.8"}]), ["8.8.8.8", "8.8.8.8"])

    def test_name_is_resolved(self) -> None:
        self.assertEqual(self.ips([{"name": "localhost"}]), ["127.0.0.1"])

    def test_unresolvable_name_is_empty(self) -> None:
        """Нерезолвящееся имя даёт пусто, а не исключение.

        Резолвер опрашивается моком, а не по-настоящему: живой отказ DNS
        стоит восемь секунд ожидания таймаута, и эта цена зависит от
        окружения, а не от кода.
        """
        with mock.patch("socket.getaddrinfo", side_effect=socket.gaierror):
            self.assertEqual(self.ips([{"name": "нет.такого.домена.invalid"}]), [])

    def test_ip_passes_through(self) -> None:
        self.assertEqual(self.ips([{"ip": "8.8.8.8"}]), ["8.8.8.8"])

    def test_unknown_hit_shape_is_ignored(self) -> None:
        self.assertEqual(self.ips([{"чепуха": 1}, {}]), [])

class ResumeTests(unittest.TestCase):
    """Возобновление с последнего записанного адреса.

    Отличие от пропуска принципиальное: сеть, целиком лежащая позади курсора,
    отбрасывается сравнением целых чисел, без единого обращения к адресу.
    Проверка на /8 ниже держится именно на этом — обход 16.7 млн адресов
    занял бы секунды.
    """

    def nets(self, *cidrs):
        return sorted(
            (ipaddress.ip_network(c) for c in cidrs),
            key=lambda n: (n.version, int(n.network_address)),
        )

    def test_without_cursor_starts_from_the_beginning(self) -> None:
        self.assertEqual(
            list(normalize.iter_from(self.nets("10.0.0.0/29"))),
            ["10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4", "10.0.0.5", "10.0.0.6"],
        )

    def test_resumes_inside_a_network(self) -> None:
        self.assertEqual(
            list(normalize.iter_from(self.nets("10.0.0.0/29"), "10.0.0.2")),
            ["10.0.0.3", "10.0.0.4", "10.0.0.5", "10.0.0.6"],
        )

    def test_whole_network_behind_the_cursor_costs_nothing(self) -> None:
        """Курсор в следующей сети — /8 позади не обходится, а отсекается."""
        nets = self.nets("10.0.0.0/8", "11.0.0.0/30")
        self.assertEqual(list(normalize.iter_from(nets, "11.0.0.1")), ["11.0.0.2"])

    def test_cursor_at_network_end_yields_nothing_from_it(self) -> None:
        self.assertEqual(list(normalize.iter_from(self.nets("10.0.0.0/30"), "10.0.0.2")), [])

    def test_resume_crosses_from_ipv4_into_ipv6(self) -> None:
        nets = self.nets("10.0.0.0/30", "2001:db8::/126")
        self.assertEqual(
            list(normalize.iter_from(nets, "10.0.0.2")),
            ["2001:db8::1", "2001:db8::2", "2001:db8::3"],
        )

    def test_per_prefix_counts_from_the_network_start(self) -> None:
        """Возобновление не должно выдавать больше, чем просили на сеть."""
        self.assertEqual(
            list(normalize.iter_from(self.nets("10.0.0.0/24"), "10.0.0.2", per_prefix=5)),
            ["10.0.0.3", "10.0.0.4", "10.0.0.5"],
        )

    def test_resume_past_the_whole_selection_yields_nothing(self) -> None:
        self.assertEqual(
            list(normalize.iter_from(self.nets("10.0.0.0/24"), "10.0.0.9", per_prefix=5)), []
        )

    def test_ipv6_cap_applies_when_resuming_too(self) -> None:
        ips = list(normalize.iter_from(self.nets("2001:db8::/32"), per_prefix=0))
        self.assertEqual(len(ips), normalize.MAX_IPV6_PER_PREFIX)

    def test_resume_deep_inside_huge_network_is_immediate(self) -> None:
        with mock.patch.object(ipaddress.IPv4Network, "hosts", side_effect=AssertionError("slow scan")):
            stream = normalize.iter_from(self.nets("10.0.0.0/8"), "10.200.0.0")
            self.assertEqual(next(stream), "10.200.0.1")

    def test_ipv6_127_and_128_include_all_hosts(self) -> None:
        self.assertEqual(list(normalize.iter_from(self.nets("2001:db8::/127"))),
                         ["2001:db8::", "2001:db8::1"])
        self.assertEqual(list(normalize.iter_from(self.nets("2001:db8::5/128"))),
                         ["2001:db8::5"])


class ResolveTests(unittest.TestCase):
    def test_parallel_resolution_keeps_name_order(self) -> None:
        with mock.patch("src.pipeline.normalize.resolve_name", side_effect=lambda name, include_ipv6: [
            "10.0.0.1" if name == "a.example.org" else "10.0.0.2"
        ]):
            rows = list(normalize.iter_resolved(["a.example.org", "b.example.org"], workers=2))
        self.assertEqual(rows, [("10.0.0.1", "a.example.org"),
                                ("10.0.0.2", "b.example.org")])

    def test_ipv6_dns_is_opt_in(self) -> None:
        answers = [
            (socket.AF_INET6, 0, 0, "", ("2001:db8::1", 0, 0, 0)),
            (socket.AF_INET, 0, 0, "", ("198.51.100.1", 0)),
        ]
        with mock.patch("socket.getaddrinfo", return_value=answers) as get:
            self.assertEqual(normalize.resolve_name("example.org", include_ipv6=True),
                             ["198.51.100.1", "2001:db8::1"])
        self.assertEqual(get.call_args.args[2], socket.AF_UNSPEC)


class MergeTests(unittest.TestCase):
    """Чистка сетей заменяет дедупликацию, которую раньше делала база."""

    def merged(self, *cidrs):
        return [str(n) for n in normalize.merge([ipaddress.ip_network(c) for c in cidrs])]

    def test_nested_network_is_dropped(self) -> None:
        self.assertEqual(self.merged("10.0.0.0/24", "10.0.0.0/25"), ["10.0.0.0/24"])

    def test_supernet_swallows_every_thing_below_it(self) -> None:
        self.assertEqual(
            self.merged("10.0.0.0/16", "10.0.0.0/24", "10.0.1.0/24"), ["10.0.0.0/16"]
        )

    def test_adjacent_networks_stay_separate(self) -> None:
        """Склеивать соседей нельзя: от каждой сети считается --per-prefix."""
        self.assertEqual(
            self.merged("10.0.0.0/25", "10.0.0.128/25"), ["10.0.0.0/25", "10.0.0.128/25"]
        )

    def test_disjoint_networks_are_untouched(self) -> None:
        self.assertEqual(self.merged("10.0.0.0/24", "10.0.2.0/24"), ["10.0.0.0/24", "10.0.2.0/24"])

    def test_result_is_sorted_even_from_unsorted_input(self) -> None:
        self.assertEqual(self.merged("10.0.1.0/24", "10.0.0.0/24"), ["10.0.0.0/24", "10.0.1.0/24"])

    def test_identical_networks_collapse_to_one(self) -> None:
        self.assertEqual(self.merged("10.0.0.0/24", "10.0.0.0/24"), ["10.0.0.0/24"])

    def test_ipv4_goes_before_ipv6(self) -> None:
        """Порядок, на который опирается iter_from: сначала IPv4, затем IPv6."""
        got = normalize.merge(
            [ipaddress.ip_network("2001:db8::/32"), ipaddress.ip_network("10.0.0.0/24")]
        )
        self.assertEqual([n.version for n in got], [4, 6])

    def test_equal_ipv6_and_ipv4_do_not_collide(self) -> None:
        """Одинаковый префикс в разных версиях — это две разные сети."""
        self.assertEqual(len(normalize.merge([ipaddress.ip_network("::/0"), ipaddress.ip_network("0.0.0.0/0")])), 2)

    def test_empty_input(self) -> None:
        self.assertEqual(normalize.merge([]), [])

    def test_address_does_not_come_out_twice(self) -> None:
        """Ради этого чистка и нужна: вложенная сеть дала бы дубли адресов."""
        networks = normalize.merge(
            [ipaddress.ip_network("10.0.0.0/24"), ipaddress.ip_network("10.0.0.0/25")]
        )
        ips = list(normalize.iter_from(networks))

        self.assertEqual(len(ips), len(set(ips)))
        self.assertEqual(len(ips), 254)


class TempStoreMixin:
    """Подменяет каталоги хранилища на временные на время теста.

    Меняются атрибуты модуля, а не переменные окружения: store читает их при
    каждом обращении, поэтому подмена действует сразу. Реальные data/ и out/
    при этом не трогаются.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.saved = (store.DATA_DIR, store.OUT_DIR, store.CACHE_ENABLED)
        store.DATA_DIR = self.root / "data"
        store.OUT_DIR = self.root / "out"
        store.CACHE_ENABLED = True
        self.addCleanup(self.restore)

    def restore(self) -> None:
        store.DATA_DIR, store.OUT_DIR, store.CACHE_ENABLED = self.saved


class StoreTests(TempStoreMixin, unittest.TestCase):
    """Файловое хранилище: кэш ответов, курсоры и файл результата."""

    # --- кэш ответов источников ---

    def test_cache_roundtrip(self) -> None:
        store.cache_put("http://x/y?z=1", "тело")
        self.assertEqual(store.cache_get("http://x/y?z=1", None), "тело")

    def test_cache_miss(self) -> None:
        self.assertIsNone(store.cache_get("http://x/нет", None))

    def test_cache_max_age_zero_is_a_miss(self) -> None:
        store.cache_put("http://x/y", "тело")
        self.assertIsNone(store.cache_get("http://x/y", 0))

    def test_cache_respects_max_age(self) -> None:
        store.cache_put("http://x/y", "тело")
        self.assertEqual(store.cache_get("http://x/y", 3600), "тело")

    def test_cache_keeps_large_bodies(self) -> None:
        """Ответы источников бывают на сотни килобайт — файл это выдержать обязан."""
        body = "x" * 400_000
        store.cache_put("http://x/big", body)
        self.assertEqual(store.cache_get("http://x/big", None), body)

    def test_cache_entry_is_readable_text(self) -> None:
        """Кэш — обычный JSON: видно глазами, можно поправить руками."""
        store.cache_put("http://x/y", "тело")
        files = list((store.DATA_DIR / "cache").glob("*.json"))

        self.assertEqual(len(files), 1)
        entry = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(entry["url"], "http://x/y")
        self.assertEqual(entry["body"], "тело")
        self.assertIsInstance(entry["fetched_at"], float)

    def test_broken_cache_file_is_a_miss_not_a_crash(self) -> None:
        store.cache_put("http://x/y", "тело")
        broken = next((store.DATA_DIR / "cache").glob("*.json"))
        broken.write_text("{ это не json", encoding="utf-8")

        self.assertIsNone(store.cache_get("http://x/y", None))

    def test_disabled_cache_reads_and_writes_nothing(self) -> None:
        store.cache_put("http://x/y", "тело")
        before = len(list((store.DATA_DIR / "cache").glob("*.json")))

        store.CACHE_ENABLED = False
        store.cache_put("http://x/z", "другое")

        self.assertEqual(len(list((store.DATA_DIR / "cache").glob("*.json"))), before)
        self.assertIsNone(store.cache_get("http://x/y", None))

    # --- курсоры ---

    def test_cursor_roundtrip(self) -> None:
        self.assertIsNone(store.get_cursor("country:LI"))
        store.set_cursor("country:LI", "10.0.0.1")
        self.assertEqual(store.get_cursor("country:LI"), "10.0.0.1")

    def test_cursor_overwrites(self) -> None:
        store.set_cursor("country:DE", "10.0.0.1")
        store.set_cursor("country:DE", "10.0.0.9")
        self.assertEqual(store.get_cursor("country:DE"), "10.0.0.9")

    def test_cursors_are_independent_per_name(self) -> None:
        store.set_cursor("country:DE", "10.0.0.1")
        store.set_cursor("country:LI", "2001:db8::1")

        self.assertEqual(store.get_cursor("country:DE"), "10.0.0.1")
        self.assertEqual(store.get_cursor("country:LI"), "2001:db8::1")

    def test_cursor_name_stays_a_valid_file_name(self) -> None:
        """Двоеточие в имени маршрута не должно ломать путь."""
        store.set_cursor("country:LI", "10.0.0.1")

        self.assertEqual(len(list((store.DATA_DIR / "state").glob("*.cursor"))), 1)
        self.assertEqual(list((store.DATA_DIR / "state").glob("*:*")), [])

    def test_cursor_survives_an_ipv6_value(self) -> None:
        store.set_cursor("country:LI", "2001:db8::1")
        self.assertEqual(store.get_cursor("country:LI"), "2001:db8::1")

    # --- файл результата ---

    def test_output_writes_one_line_per_record(self) -> None:
        path = self.root / "out" / "ips.txt"
        with store.Output(path) as out:
            out.write("10.0.0.1")
            out.write("10.0.0.2")

        self.assertEqual(path.read_text(encoding="utf-8"), "10.0.0.1\n10.0.0.2\n")
        self.assertEqual(out.count, 2)

    def test_output_creates_missing_directories(self) -> None:
        path = self.root / "nested" / "deep" / "ips.txt"
        with store.Output(path) as out:
            out.write("10.0.0.1")

        self.assertTrue(path.is_file())

    def test_output_keeps_tab_separated_hosts(self) -> None:
        """CT-маршрут пишет пару «адрес<TAB>имя» — она должна читаться как есть."""
        path = self.root / "ct.txt"
        with store.Output(path) as out:
            out.write("10.0.0.1\twww.example.org")

        ip, host = path.read_text(encoding="utf-8").strip().split("\t")
        self.assertEqual((ip, host), ("10.0.0.1", "www.example.org"))

    def test_output_append_keeps_previous_lines(self) -> None:
        path = self.root / "all.txt"
        with store.Output(path) as out:
            out.write("10.0.0.1")
        with store.Output(path, append=True) as out:
            out.write("10.0.0.2")

        self.assertEqual(path.read_text(encoding="utf-8"), "10.0.0.1\n10.0.0.2\n")

    def test_output_overwrites_by_default(self) -> None:
        path = self.root / "all.txt"
        with store.Output(path) as out:
            out.write("10.0.0.1")
        with store.Output(path) as out:
            out.write("10.0.0.2")

        self.assertEqual(path.read_text(encoding="utf-8"), "10.0.0.2\n")

    def test_on_flush_fires_only_on_flushed_lines(self) -> None:
        """Курсор обязан двигаться только по сброшенному: иначе уедет вперёд файла."""
        seen: list[str] = []
        with store.Output(self.root / "ips.txt", flush_every=3, on_flush=seen.append) as out:
            for i in range(1, 8):
                out.write(f"10.0.0.{i}")

        self.assertEqual(seen, ["10.0.0.3", "10.0.0.6", "10.0.0.7"])

    def test_on_flush_is_silent_for_an_empty_run(self) -> None:
        seen: list[str] = []
        with store.Output(self.root / "empty.txt", on_flush=seen.append):
            pass

        self.assertEqual(seen, [])

    def test_interrupted_run_leaves_cursor_and_file_consistent(self) -> None:
        """После Ctrl+C курсор указывает на последнюю строку, которая уже в файле."""
        path = self.root / "ips.txt"
        seen: list[str] = []

        with self.assertRaises(KeyboardInterrupt):
            with store.Output(path, flush_every=2, on_flush=seen.append) as out:
                for i in range(1, 6):
                    out.write(f"10.0.0.{i}")
                    if i == 3:
                        raise KeyboardInterrupt

        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines, ["10.0.0.1", "10.0.0.2", "10.0.0.3"])
        self.assertEqual(seen[-1], lines[-1])

    def test_output_path_default_carries_route_and_extension(self) -> None:
        path = store.output_path("country", None)

        self.assertEqual(path.parent, store.OUT_DIR)
        self.assertTrue(path.name.startswith("country_"))
        self.assertTrue(path.name.endswith(".txt"))

    def test_output_path_explicit_wins(self) -> None:
        self.assertEqual(store.output_path("country", "/tmp/my.txt"), Path("/tmp/my.txt"))


class FetchCacheTests(TempStoreMixin, unittest.TestCase):
    """Сеть дёргается один раз: дальше ответ приходит из файлового кэша."""

    def response(self, status: int, text: str):
        stub = mock.Mock(status_code=status, text=text)
        stub.raise_for_status = mock.Mock()
        return stub

    def test_second_call_comes_from_cache(self) -> None:
        with mock.patch("src.pipeline.fetch.requests.get", return_value=self.response(200, '{"ok": true}')) as get:
            first = fetch.fetch_json("http://example.invalid/data")
            second = fetch.fetch_json("http://example.invalid/data")

        self.assertEqual(first, second)
        self.assertEqual(get.call_count, 1)

    def test_errors_are_not_cached(self) -> None:
        with mock.patch("src.pipeline.fetch.requests.get", return_value=self.response(500, "boom")) as get:
            with mock.patch("src.pipeline.fetch.time.sleep"):
                with self.assertRaises(RuntimeError):
                    fetch.fetch_text("http://example.invalid/x", tries=2)

        self.assertEqual(get.call_count, 2)
        self.assertIsNone(store.cache_get("http://example.invalid/x?", None))

    def test_invalid_json_is_retried_and_not_cached(self) -> None:
        replies = [self.response(200, "not json"), self.response(200, '{"ok": true}')]
        with mock.patch("src.pipeline.fetch.requests.get", side_effect=replies) as get:
            with mock.patch("src.pipeline.fetch.time.sleep"):
                self.assertEqual(fetch.fetch_json("http://example.invalid/json", tries=2), {"ok": True})
        self.assertEqual(get.call_count, 2)
        self.assertEqual(store.cache_get("http://example.invalid/json?", None), '{"ok": true}')

    def test_corrupt_cached_json_is_refetched(self) -> None:
        store.cache_put("http://example.invalid/json?", "broken")
        with mock.patch("src.pipeline.fetch.requests.get", return_value=self.response(200, "[]")):
            self.assertEqual(fetch.fetch_json("http://example.invalid/json"), [])

    def test_api_error_inside_http_200_is_not_cached(self) -> None:
        bad = self.response(200, '{"status": "error", "data": {}}')
        with mock.patch("src.pipeline.fetch.requests.get", return_value=bad) as get:
            with mock.patch("src.pipeline.fetch.time.sleep"):
                with self.assertRaises(RuntimeError):
                    fetch.fetch_json(
                        "http://example.invalid/json",
                        validate=lambda payload: sources._data(payload, "LI"),
                        tries=2,
                    )
        self.assertEqual(get.call_count, 2)
        self.assertIsNone(store.cache_get("http://example.invalid/json?", None))


class CliTests(TempStoreMixin, unittest.TestCase):
    def test_asn_output_and_resume(self) -> None:
        networks = [ipaddress.ip_network("198.51.100.0/29")]
        with mock.patch("src.main.sources.asn", return_value=networks):
            with mock.patch("sys.stdout"):
                self.assertEqual(main.main(["--asn", "AS64500", "--no-ipv6", "--max-addresses", "2"]), 0)
                self.assertEqual(main.main(["--asn", "AS64500", "--no-ipv6", "--max-addresses", "2"]), 0)
        outputs = sorted(store.OUT_DIR.glob("asn_*.txt"))
        self.assertEqual([path.read_text().splitlines() for path in outputs],
                         [["198.51.100.1", "198.51.100.2"],
                          ["198.51.100.3", "198.51.100.4"]])

    def test_existing_output_is_preserved(self) -> None:
        path = store.OUT_DIR / "saved.txt"
        path.parent.mkdir(parents=True)
        path.write_text("important\n")
        with mock.patch("src.main.sources.country", return_value=(
            [ipaddress.ip_network("198.51.100.0/30")], []
        )):
            with mock.patch("sys.stdout"):
                self.assertEqual(main.main(["LI", "--out", str(path)]), 1)
        self.assertEqual(path.read_text(), "important\n")

    def test_force_replaces_existing_output(self) -> None:
        path = store.OUT_DIR / "saved.txt"
        path.parent.mkdir(parents=True)
        path.write_text("old\n")
        with mock.patch("src.main.sources.country", return_value=(
            [ipaddress.ip_network("198.51.100.0/30")], []
        )):
            with mock.patch("sys.stdout"), mock.patch("sys.stderr"):
                self.assertEqual(main.main(["LI", "--out", str(path), "--force"]), 0)
        self.assertEqual(path.read_text().splitlines(), ["198.51.100.1", "198.51.100.2"])

    def test_changed_selection_uses_new_cursor(self) -> None:
        networks = [ipaddress.ip_network("198.51.100.0/29")]
        with mock.patch("src.main.sources.country", return_value=(networks, [])):
            with mock.patch("sys.stdout"):
                self.assertEqual(main.main(["LI", "--per-prefix", "2"]), 0)
                self.assertEqual(main.main(["LI", "--per-prefix", "3"]), 0)
        outputs = sorted(store.OUT_DIR.glob("country_*.txt"))
        self.assertEqual(outputs[1].read_text().splitlines(),
                         ["198.51.100.1", "198.51.100.2", "198.51.100.3"])

    def test_changed_network_snapshot_uses_new_cursor(self) -> None:
        first = [ipaddress.ip_network("198.51.100.0/30")]
        second = [ipaddress.ip_network("198.51.100.0/29")]
        with mock.patch("src.main.sources.country", side_effect=[(first, []), (second, [])]):
            with mock.patch("sys.stdout"), mock.patch("sys.stderr"):
                self.assertEqual(main.main(["LI", "--max-addresses", "1"]), 0)
                self.assertEqual(main.main(["LI", "--max-addresses", "1"]), 0)
        outputs = sorted(store.OUT_DIR.glob("country_*.txt"))
        self.assertEqual([path.read_text().strip() for path in outputs],
                         ["198.51.100.1", "198.51.100.1"])


if __name__ == "__main__":
    unittest.main()
