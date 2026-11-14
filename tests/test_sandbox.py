"""Offline tests for the sandbox network guard (sandbox/netguard.py). No Playwright, no network."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sandbox"))
from netguard import CachingGuard, is_public_ip, parse_ip_literal, url_allowed  # noqa: E402

PUBLIC = "93.184.215.14"


def fake_resolver(table):
    def resolve(host):
        if host not in table:
            raise OSError("NXDOMAIN")
        return table[host]
    return resolve


DNS = fake_resolver({
    "example.com": [PUBLIC, "2606:2800:21f:cb07:6820:80da:af6b:8b2c"],
    "evil-internal.test": ["10.0.0.5"],
    "metadata-rebind.test": ["169.254.169.254"],
    "mixed.test": [PUBLIC, "127.0.0.1"],      # ANY private answer blocks
    "v6local.test": ["::1"],
    "mapped.test": ["::ffff:192.168.1.1"],
    "empty.test": [],
})


@pytest.mark.parametrize("ip", [
    "127.0.0.1", "127.8.9.10", "10.1.2.3", "172.16.0.1", "172.31.255.255", "192.168.1.1",
    "169.254.169.254", "169.254.0.1", "100.64.0.1", "100.127.255.254", "0.0.0.0",
    "224.0.0.1", "239.255.255.250", "255.255.255.255", "240.0.0.1", "198.18.0.1",
    "::1", "::", "fc00::1", "fd12:3456::1", "fe80::1", "fe80::1%eth0", "ff02::1",
    "::ffff:127.0.0.1", "::ffff:169.254.169.254", "64:ff9b::a9fe:a9fe",  # NAT64 -> metadata
    "2002:c0a8:0101::1",                                                # 6to4 -> 192.168.1.1
    "fd00:ec2::254",                                                    # AWS IPv6 metadata
    "not-an-ip", "",
])
def test_non_public_ips_blocked(ip):
    assert not is_public_ip(ip)


@pytest.mark.parametrize("ip", [PUBLIC, "8.8.8.8", "1.1.1.1", "2606:4700:4700::1111",
                                "2001:4860:4860::8888", "::ffff:8.8.8.8"])
def test_public_ips_allowed(ip):
    assert is_public_ip(ip)


@pytest.mark.parametrize("host,expected", [
    ("2130706433", "127.0.0.1"),          # decimal
    ("0x7f000001", "127.0.0.1"),          # hex
    ("0177.0.0.1", "127.0.0.1"),          # octal
    ("127.1", "127.0.0.1"),               # short form
    ("0x7f.0.0.1", "127.0.0.1"),
    ("3232235777", "192.168.1.1"),
    ("[::1]", "::1"),
    ("example.com", None),
])
def test_ip_literal_parsing(host, expected):
    got = parse_ip_literal(host)
    assert (str(got) if got else None) == expected


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://10.0.0.1/admin", "http://172.16.5.5/", "http://192.168.0.1/",
    "http://169.254.169.254/latest/meta-data/", "http://[::1]:8080/", "http://[fc00::1]/",
    "http://[fd00::abcd]/", "http://[fe80::1]/", "http://100.64.1.1/", "http://0.0.0.0:8080/",
    "http://localhost/", "http://LOCALHOST./", "http://foo.localhost/", "http://printer.local/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://2130706433/", "http://0x7f000001/", "http://0177.0.0.1/", "http://127.1/",
    "http://[::ffff:127.0.0.1]/", "http://[::ffff:7f00:1]/",
    "http://256.256.256.256/", "http://99999999999/",
    "file:///etc/passwd", "javascript:alert(1)", "data:text/html,hi", "ftp://example.com/",
    "chrome://settings", "about:blank", "ws://example.com/", "gopher://example.com/",
    "http://user:pass@example.com/", "http://example.com@127.0.0.1/",
    "http://evil-internal.test/", "http://metadata-rebind.test/", "http://mixed.test/",
    "http://v6local.test/", "http://mapped.test/", "http://empty.test/", "http://nxdomain.test/",
    "http:///nohost", "http://example.com:99999/", "http://exa\nmple.com/", "",
    "https://example.com/" + "a" * 3000,
])
def test_urls_blocked(url):
    ok, reason = url_allowed(url, resolver=DNS)
    assert not ok, reason


@pytest.mark.parametrize("url", [
    "https://example.com/", "http://example.com/pay?meter=42", "HTTPS://EXAMPLE.COM/",
    f"http://{PUBLIC}/", "https://[2606:4700:4700::1111]/", "https://example.com:8443/x",
])
def test_urls_allowed(url):
    ok, reason = url_allowed(url, resolver=DNS)
    assert ok, reason


def test_resolver_not_called_for_ip_literals_or_bad_schemes():
    calls = []
    def spy(host):
        calls.append(host)
        return [PUBLIC]
    url_allowed("http://2130706433/", resolver=spy)
    url_allowed("file:///etc/passwd", resolver=spy)
    url_allowed("http://localhost/", resolver=spy)
    assert calls == []


def test_caching_guard_keeps_first_answer():
    """A host that flips to a private IP mid-scan (DNS rebinding) keeps its first decision,
    and a host that is private on first lookup stays blocked."""
    answers = {"flip.test": [[PUBLIC], ["127.0.0.1"]]}
    def flipping(host):
        return answers[host].pop(0) if len(answers[host]) > 1 else answers[host][0]
    g = CachingGuard(resolver=flipping)
    assert g.check("https://flip.test/a")[0]
    assert g.check("https://flip.test/b")[0]   # same cached public answer, no re-resolve
    g2 = CachingGuard(resolver=DNS)
    assert not g2.check("http://evil-internal.test/")[0]
    assert g2.check("https://example.com/")[0]


def test_netguard_has_no_playwright_dependency():
    import netguard
    src = open(netguard.__file__).read()
    assert "playwright" not in src.split('"""', 2)[2].lower()
