"""A self-signed certificate for the hub, so phones on the LAN get https and the microphone (W5).

Browsers only allow the microphone on https (or localhost). On demo day the
preferred path is a tunnel with a real certificate (docs/15 section 2). This is
the no-internet fallback: `python -m unstep.live --host 0.0.0.0 --https` makes a
certificate for localhost, 127.0.0.1 and this machine's LAN address, stored under
data/certs/ (gitignored). Each phone has to accept the certificate warning once
by opening the hub's https address directly before the pilot app can connect.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import shutil
import subprocess
from pathlib import Path

from unstep.config import ROOT

CERT_DIR = ROOT / "data" / "certs"


def _names(hosts: list[str]) -> tuple[list[str], list[str]]:
    dns, ips = [], []
    for h in dict.fromkeys(["localhost", "127.0.0.1", *hosts]):
        if not h:
            continue
        try:
            ipaddress.ip_address(h)
            ips.append(h)
        except ValueError:
            dns.append(h)
    return dns, ips


def self_signed(hosts: list[str], directory: Path = CERT_DIR, days: int = 30) -> tuple[Path, Path]:
    """Write (cert.pem, key.pem) valid for the given hosts and return their paths.

    Reuses an existing pair made for the same hosts. Uses the `cryptography`
    package when installed, otherwise the openssl command line tool.
    """
    dns, ips = _names(hosts)
    directory.mkdir(parents=True, exist_ok=True)
    cert, key = directory / "hub-cert.pem", directory / "hub-key.pem"
    stamp = directory / "hosts.txt"
    wanted = ",".join(dns + ips)
    if cert.exists() and key.exists() and stamp.exists() and stamp.read_text() == wanted:
        return cert, key
    try:
        _with_cryptography(dns, ips, cert, key, days)
    except ImportError:
        _with_openssl(dns, ips, cert, key, days)
    key.chmod(0o600)
    stamp.write_text(wanted)
    return cert, key


def _with_cryptography(dns, ips, cert: Path, key: Path, days: int) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    private = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Unstep hub (self-signed)")])
    now = dt.datetime.now(dt.timezone.utc)
    san = x509.SubjectAlternativeName([*(x509.DNSName(d) for d in dns),
                                       *(x509.IPAddress(ipaddress.ip_address(i)) for i in ips)])
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                   .public_key(private.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=days))
                   .add_extension(san, critical=False)
                   .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                   .sign(private, hashes.SHA256()))
    key.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))


def _with_openssl(dns, ips, cert: Path, key: Path, days: int) -> None:
    if not shutil.which("openssl"):
        raise RuntimeError("need the cryptography package or openssl to make a certificate; "
                           "or pass --cert and --key")
    san = ",".join([*(f"DNS:{d}" for d in dns), *(f"IP:{i}" for i in ips)])
    subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                    "-nodes", "-keyout", str(key), "-out", str(cert), "-days", str(days),
                    "-subj", "/CN=Unstep hub (self-signed)", "-addext", f"subjectAltName={san}"],
                   check=True, capture_output=True)
