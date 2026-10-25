"""Addresses people can use to reach this hub, for the console's "change link" choice.

The console's QR opens the pilot app at the hub's own address, which is `localhost` when the tower
runs on the laptop: that link only works on the laptop. These helpers list the addresses a phone or a
Raspberry Pi could use instead (the same wifi, a public link) and say which hosts this hub may put in a QR.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

LOOPBACK_BINDS = ("127.0.0.1", "localhost", "::1", "[::1]")


def lan_addresses() -> list[str]:
    """This machine's private IPv4 addresses (wifi, Ethernet, a shared hotspot), the one the OS would route
    out through first. Loopback and link-local (169.254.x.x) addresses are left out: nobody else can use them."""
    found: list[str] = []

    def add(ip: str) -> None:
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            return
        if address.version == 4 and address.is_private and not address.is_loopback \
                and not address.is_link_local and ip not in found:
            found.append(ip)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent; it only picks the outgoing interface
            add(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(info[4][0])
    except OSError:
        pass
    return found


def reachable_from_lan(bind_host: str | None) -> bool:
    """False only when the hub is known to listen on this computer alone (the default `--host 127.0.0.1`)."""
    return bind_host is None or bind_host not in LOOPBACK_BINDS


def own_hostnames(public_url: str | None) -> set[str]:
    """Hosts this hub may put in a join link or QR code: its own LAN addresses and its public address."""
    hosts = set(lan_addresses())
    public_host = urlsplit(public_url or "").hostname
    if public_host:
        hosts.add(public_host)
    return hosts
