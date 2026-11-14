"""Pure-Python destination checks for the sandbox browser (no Playwright import here).

Used in two places:
  - sandbox/server.py  -> validate the QR URL before a container is even started
  - sandbox/run_scan.py -> inside the container, on EVERY browser request (first URL, each
    redirect hop, subresources, popups) via context.route("**/*", ...)

Rule: a request is allowed only if its scheme is http/https, it has no embedded credentials,
and EVERY address its hostname resolves to is a public unicast address. Anything else
(loopback, RFC1918, link-local incl. 169.254.169.254 metadata, CGNAT, multicast, reserved,
IPv6 ULA/link-local, IPv4-mapped/NAT64/6to4 wrappers around those) is blocked.

This is an application-layer check. It cannot fully stop DNS rebinding (the browser resolves
again after we check), so the sandbox VM must ALSO drop private egress at the firewall; see
sandbox/README.md.
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Callable, Iterable
from urllib.parse import urlsplit

ALLOWED_SCHEMES = {"http", "https"}
MAX_URL_LEN = 2000

# Hostnames that must never be fetched regardless of what DNS says.
BLOCKED_HOSTNAMES = {
    "localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback",
    "metadata", "metadata.google.internal", "metadata.goog", "instance-data",
}
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".intranet")

# Ranges Python's ipaddress may still call "global" or that we want named explicitly.
_EXTRA_BLOCKED = [ipaddress.ip_network(n) for n in (
    "0.0.0.0/8",          # "this network"; 0.0.0.0 reaches localhost on Linux
    "100.64.0.0/10",      # CGNAT (also not is_global, listed for clarity)
    "192.0.0.0/24",       # IETF protocol assignments
    "192.88.99.0/24",     # 6to4 relay anycast (deprecated)
    "198.18.0.0/15",      # benchmarking
    "224.0.0.0/4",        # multicast
    "240.0.0.0/4",        # reserved + broadcast
    "::/128", "::1/128",
    "fc00::/7",           # unique local
    "fe80::/10",          # link-local
    "fec0::/10",          # deprecated site-local
    "ff00::/8",           # multicast
    "100::/64",           # discard-only
    "2001:db8::/32",      # documentation
)]

Resolver = Callable[[str], Iterable[str]]


def _embedded_ipv4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """IPv4 address hidden inside an IPv6 wrapper (mapped, compat, NAT64, 6to4, Teredo)."""
    if ip.ipv4_mapped:
        return ip.ipv4_mapped
    if ip.sixtofour:
        return ip.sixtofour
    if ip.teredo:
        return ip.teredo[1]
    packed = ip.packed
    if ip in ipaddress.ip_network("64:ff9b::/96") or ip in ipaddress.ip_network("64:ff9b:1::/48"):
        return ipaddress.IPv4Address(packed[-4:])
    if packed[:12] == b"\x00" * 12 and packed[12:] != b"\x00\x00\x00\x00":  # ::a.b.c.d (compat)
        return ipaddress.IPv4Address(packed[-4:])
    return None


def is_public_ip(value: str | ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True only for public unicast addresses. Unparseable input -> False (fail closed)."""
    try:
        ip = value if not isinstance(value, str) else ipaddress.ip_address(value.strip("[]").split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        inner = _embedded_ipv4(ip)
        if inner is not None and not is_public_ip(inner):
            return False
    if any(ip in net for net in _EXTRA_BLOCKED if net.version == ip.version):
        return False
    if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
            or ip.is_reserved or ip.is_unspecified or not ip.is_global):
        return False
    return True


def parse_ip_literal(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse host the way browsers do (WHATWG URL spec), so tricks like 2130706433,
    0x7f000001, 0177.0.0.1, 127.1 and [::ffff:127.0.0.1] are recognised as IPs."""
    h = host.strip().rstrip(".").lower()
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    if ":" in h:
        try:
            return ipaddress.IPv6Address(h.split("%")[0])
        except ValueError:
            return None
    parts = h.split(".")
    if not parts or len(parts) > 4 or any(p == "" for p in parts):
        return None
    nums = []
    for p in parts:
        try:
            if p.startswith(("0x", "0X")):
                n = int(p[2:] or "0", 16)
            elif len(p) > 1 and p.startswith("0"):
                n = int(p[1:], 8)
            else:
                n = int(p, 10)
        except ValueError:
            return None  # contains a non-numeric label -> a hostname, not an IP
        nums.append(n)
    *head, last = nums
    if any(n > 255 for n in head) or last >= 256 ** (5 - len(nums)):
        return None  # browsers reject these outright; treat as invalid (caller blocks)
    value = 0
    for n in head:
        value = value * 256 + n
    value = value * 256 ** (5 - len(nums)) + last
    return ipaddress.IPv4Address(value)


def _ends_in_number(host: str) -> bool:
    """WHATWG 'ends in a number' check: last label is all digits or 0x-hex."""
    last = host.rstrip(".").split(".")[-1]
    if last.isdigit():
        return True
    return last.startswith("0x") and all(c in "0123456789abcdef" for c in last[2:])


def system_resolver(host: str) -> list[str]:
    """All A/AAAA answers for host. Raises OSError if it doesn't resolve."""
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return sorted({info[4][0] for info in infos})


def url_allowed(url: str, resolver: Resolver = system_resolver) -> tuple[bool, str]:
    """(allowed, reason). Fails closed: anything unparseable or unresolvable is blocked."""
    if not isinstance(url, str) or not url or len(url) > MAX_URL_LEN:
        return False, "missing or too-long URL"
    if any(c in url for c in "\r\n\t\x00"):
        return False, "control characters in URL"
    try:
        parts = urlsplit(url.strip())
        scheme = parts.scheme.lower()
        host = parts.hostname  # lowercased, brackets stripped
        _ = parts.port         # raises ValueError on a bad port
    except ValueError:
        return False, "malformed URL"
    if scheme not in ALLOWED_SCHEMES:
        return False, f"scheme {scheme or '(none)'!r} not allowed"
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        return False, "credentials embedded in URL"
    if not host:
        return False, "no hostname"
    host = host.rstrip(".")
    if host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_SUFFIXES):
        return False, f"internal hostname {host!r}"

    literal = parse_ip_literal(host)
    if literal is not None:
        if not is_public_ip(literal):
            return False, f"non-public address {literal}"
        return True, f"public address {literal}"
    if _ends_in_number(host):
        # Browsers treat these as IPv4 and reject them if out of range (256.1.1.1,
        # 99999999999); never hand them to DNS where some resolver might accept them.
        return False, "invalid numeric host"

    try:
        addrs = list(resolver(host))
    except (OSError, UnicodeError, ValueError) as e:
        return False, f"DNS lookup failed: {type(e).__name__}"
    if not addrs:
        return False, "hostname did not resolve"
    bad = [a for a in addrs if not is_public_ip(a)]
    if bad:
        return False, f"{host} resolves to non-public address {bad[0]}"
    return True, f"{host} -> {', '.join(addrs[:4])}"


class CachingGuard:
    """url_allowed with a per-scan cache of host decisions (one container = one scan),
    so a page with 200 subresources on one CDN does one lookup, and a host that changes
    its DNS answer mid-scan keeps the FIRST decision (blocks naive rebinding)."""

    def __init__(self, resolver: Resolver = system_resolver):
        self.resolver = resolver
        self._hosts: dict[str, list[str]] = {}

    def _cached_resolver(self, host: str) -> list[str]:
        if host not in self._hosts:
            self._hosts[host] = list(self.resolver(host))
        return self._hosts[host]

    def check(self, url: str) -> tuple[bool, str]:
        return url_allowed(url, self._cached_resolver)
