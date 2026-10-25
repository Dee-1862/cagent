"""429 backoff on the Cartesia handshake and caption settling (offline)."""
import asyncio

import pytest

import unstep.cockpit.cartesia_errors as ce
from unstep.cockpit.cartesia_errors import CartesiaRateLimited, connect_with_backoff, is_rate_limited
from unstep.cockpit.stt import settle_caption


class Resp:
    def __init__(self, code):
        self.status_code = code


class Status(Exception):
    def __init__(self, code):
        self.response = Resp(code)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def fast(_s):
        return None
    monkeypatch.setattr(ce.asyncio, "sleep", fast)


def test_is_rate_limited():
    assert is_rate_limited(Status(429))
    assert not is_rate_limited(Status(401))
    assert is_rate_limited(CartesiaRateLimited("x"))
    assert not is_rate_limited(OSError())


def test_retries_429_then_connects():
    calls = []

    async def open_socket():
        calls.append(1)
        if len(calls) < 3:
            raise Status(429)
        return "ws"

    assert asyncio.run(connect_with_backoff(open_socket)) == "ws"
    assert len(calls) == 3


def test_gives_up_with_clear_error():
    async def open_socket():
        raise Status(429)

    with pytest.raises(CartesiaRateLimited, match="429"):
        asyncio.run(connect_with_backoff(open_socket))


def test_other_errors_pass_through_immediately():
    calls = []

    async def open_socket():
        calls.append(1)
        raise Status(401)

    with pytest.raises(Status):
        asyncio.run(connect_with_backoff(open_socket))
    assert calls == [1]


def test_settle_caption_holds_back_a_possibly_split_word():
    assert settle_caption("Cess") == ""
    assert settle_caption("Cessna one two thirty-") == "Cessna one two"
    assert settle_caption("Cessna one two thirty-three", final=True) == "Cessna one two thirty-three"
