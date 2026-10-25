"""429 backoff on the Cartesia handshake and caption settling (offline)."""
import asyncio
import json
import logging

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


# ---------------------------------------------------------------- what a 429 looked like (status, body, sockets)

class Resp429:
    """Like a websockets handshake response: status, a body, and headers that must never be logged."""
    status_code = 429
    body = b'{"error_code": "concurrency_limited", "message": "Too many concurrent requests"}'
    headers = {"X-API-Key": "sk_headers_must_not_appear", "Retry-After": "1"}


class Handshake429(Exception):
    response = Resp429()


@pytest.fixture
def clean_state(monkeypatch):
    ce._open.clear()
    ce.RATE_LIMIT_EVENTS.clear()
    monkeypatch.setenv("CARTESIA_API_KEY", "sk_test_secret_value")
    yield
    ce._open.clear()
    ce.RATE_LIMIT_EVENTS.clear()


def test_handshake_429_is_logged_with_status_body_and_open_sockets(clean_state, caplog):
    ce.socket_opened("tts")
    ce.socket_opened("stt")
    with caplog.at_level(logging.WARNING, logger="unstep.cartesia"):
        detail = ce.log_rate_limited(Handshake429(), "handshake")
    assert detail["status"] == 429 and "concurrency_limited" in detail["body"]
    assert detail["open_sockets"] == 2 and detail["open_by_kind"] == {"tts": 1, "stt": 1}
    text = caplog.text
    assert "429" in text and "concurrency_limited" in text and "open_sockets=2" in text
    assert "sk_headers_must_not_appear" not in text and "Retry-After" not in text  # never headers
    assert list(ce.RATE_LIMIT_EVENTS) == [detail]


def test_secrets_are_removed_and_body_is_truncated(clean_state):
    class Leaky(Exception):
        response = type("R", (), {"status_code": 429, "body": ("echo sk_test_secret_value Bearer abc.def " + "x" * 2000)})()

    detail = ce.rate_limit_detail(Leaky(), "x")
    assert "sk_test_secret_value" not in detail["body"] and "abc.def" not in detail["body"]
    assert "[redacted]" in detail["body"] and len(detail["body"]) <= ce.BODY_LIMIT


def test_error_event_keeps_only_describing_fields(clean_state):
    event = {"type": "error", "status_code": 429, "title": "Too many", "message": "slow down",
             "context_id": "c1", "api_key": "sk_test_secret_value"}
    exc = ce.rate_limited_from_event(event, "tts")
    assert isinstance(exc, CartesiaRateLimited) and exc.status == 429
    assert "slow down" in exc.body and "c1" not in exc.body and "sk_test" not in exc.body


def test_giving_up_carries_the_last_body_and_socket_count(clean_state):
    ce.socket_opened("tts")

    async def open_socket():
        raise Handshake429()

    with pytest.raises(CartesiaRateLimited) as info:
        asyncio.run(connect_with_backoff(open_socket))
    assert info.value.status == 429 and "concurrency_limited" in info.value.body and info.value.open_sockets == 1
    assert len(ce.RATE_LIMIT_EVENTS) == 3  # one per attempt


def test_socket_counter_never_goes_negative(clean_state):
    ce.socket_closed("tts")
    assert ce.open_socket_count() == 0
    ce.socket_opened("tts")
    ce.socket_closed("tts")
    assert ce.open_socket_count() == 0 and ce.open_socket_counts() == {}


class FakeWS:
    def __init__(self, messages=()):
        self.messages = list(messages)
        self.sent = []
        self.close_code = None

    async def send(self, data):
        self.sent.append(data)

    async def recv(self):
        return json.dumps(self.messages.pop(0))

    async def close(self):
        self.close_code = 1000


def test_tts_counts_its_socket_and_a_429_event_is_logged(clean_state, monkeypatch):
    from unstep.cockpit.tts import CartesiaTTS

    ws = FakeWS([{"type": "error", "status_code": 429, "title": "Too many", "message": "limit", "context_id": "c"}])

    async def fake_connect(*a, **kw):
        return ws

    monkeypatch.setattr("websockets.connect", fake_connect)
    tts = CartesiaTTS(api_key="k", voice_id="v")

    async def go():
        try:
            with pytest.raises(CartesiaRateLimited) as info:
                await tts.speak("hello", context_id="c")
            assert ce.open_socket_count() == 1  # open at the moment of the 429
            return info.value
        finally:
            await tts.close()

    exc = asyncio.run(go())
    assert exc.open_sockets == 1 and "limit" in exc.body
    assert ce.RATE_LIMIT_EVENTS[-1]["open_sockets"] == 1
    assert ce.open_socket_count() == 0  # close() lowered it


def test_stt_counts_and_releases_its_socket(clean_state, monkeypatch):
    from unstep.cockpit.stt import CartesiaManualSTT, CartesiaTurnSTT

    sockets = []

    async def fake_connect(*a, **kw):
        sockets.append(FakeWS())
        return sockets[-1]

    monkeypatch.setattr("websockets.connect", fake_connect)

    async def go():
        async with CartesiaManualSTT(api_key="k"):
            async with CartesiaTurnSTT(api_key="k"):
                assert ce.open_socket_count() == 2
        assert ce.open_socket_count() == 0

    asyncio.run(go())
    assert all(s.close_code == 1000 for s in sockets)


def test_stt_error_event_429_raises_rate_limited(clean_state):
    from unstep.cockpit.stt import CartesiaManualSTT

    stt = CartesiaManualSTT(api_key="k")
    with pytest.raises(CartesiaRateLimited, match="STT"):
        stt._take({"type": "error", "status_code": 429, "title": "Too many", "message": "slow down"})
    with pytest.raises(RuntimeError) as other:
        stt._take({"type": "error", "status_code": 500, "title": "Oops", "message": "x"})
    assert not isinstance(other.value, CartesiaRateLimited)
