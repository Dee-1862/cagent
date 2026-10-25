"""W5: the hub can serve https (self-signed or given cert), so phone microphones work on the LAN."""

import asyncio
import os
import shutil
import socket
import ssl
import subprocess
import sys
import time

import pytest

from unstep.config import ROOT
from unstep.live import certs


def _sans(cert_path):
    out = subprocess.run(["openssl", "x509", "-in", str(cert_path), "-noout", "-ext", "subjectAltName"],
                         capture_output=True, text=True, check=True).stdout
    return out


@pytest.mark.skipif(not shutil.which("openssl"), reason="openssl CLI needed to read the certificate")
def test_self_signed_covers_localhost_and_lan_ip_and_is_reused(tmp_path):
    cert, key = certs.self_signed(["192.168.1.20", "hub.local"], directory=tmp_path)
    sans = _sans(cert)
    for name in ("localhost", "hub.local", "127.0.0.1", "192.168.1.20"):
        assert name in sans
    if sys.platform != "win32":  # Windows has no Unix permission bits; chmod 0o600 reads back as 0o666
        assert oct(key.stat().st_mode & 0o777) == "0o600"
    first = cert.read_bytes()
    assert certs.self_signed(["192.168.1.20", "hub.local"], directory=tmp_path)[0].read_bytes() == first
    assert certs.self_signed(["192.168.1.21"], directory=tmp_path)[0].read_bytes() != first  # new host, new cert


@pytest.mark.skipif(not shutil.which("openssl"), reason="openssl CLI needed")
def test_openssl_fallback_when_cryptography_is_missing(tmp_path, monkeypatch):
    def no_crypto(*a, **k):
        raise ImportError("no cryptography")

    monkeypatch.setattr(certs, "_with_cryptography", no_crypto)
    cert, _ = certs.self_signed(["10.0.0.5"], directory=tmp_path)
    assert "10.0.0.5" in _sans(cert)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_hub_serves_https_and_wss(tmp_path):
    import httpx
    import websockets

    cert, key = certs.self_signed([], directory=tmp_path)
    port = _free_port()
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    env.pop("CARTESIA_API_KEY", None)
    proc = subprocess.Popen([sys.executable, "-m", "unstep.live", "--offline", "--no-browser", "--port", str(port),
                             "--cert", str(cert), "--key", str(key)], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        ctx = ssl.create_default_context(cafile=str(cert))  # trust exactly this self-signed cert
        deadline = time.time() + 20
        while True:
            try:
                r = httpx.get(f"https://127.0.0.1:{port}/live/atc/", verify=ctx, timeout=2, trust_env=False)
                break
            except httpx.TransportError:
                if time.time() > deadline or proc.poll() is not None:
                    raise
                time.sleep(0.2)
        assert r.status_code == 200

        async def ws():
            async with websockets.connect(f"wss://127.0.0.1:{port}/live/ws/observer", ssl=ctx, proxy=None) as w:
                return await asyncio.wait_for(w.recv(), 5)

        assert '"hello"' in asyncio.run(ws())
    finally:
        proc.terminate()
        proc.wait(10)
