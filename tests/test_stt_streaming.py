"""Live captions: ink-2 streams final text deltas while audio is still arriving."""
import asyncio
import json

import unstep.cockpit.stt as stt_mod
from unstep.cockpit.stt import CartesiaManualSTT


class FakeWS:
    """Replies to each audio frame with one delta; to `finalize` with the utterance's tail and flush_done."""

    def __init__(self, utterances):
        self.utterances, self.inbox = [list(u) for u in utterances], asyncio.Queue()
        self.deltas = self.utterances.pop(0)

    async def send(self, data):
        if data == "finalize":
            for d in self.deltas:
                await self.inbox.put({"type": "transcript", "is_final": True, "text": d})
            self.deltas = self.utterances.pop(0) if self.utterances else []
            await self.inbox.put({"type": "flush_done"})
        elif isinstance(data, bytes) and self.deltas:
            await self.inbox.put({"type": "transcript", "is_final": True, "text": self.deltas.pop(0)})

    async def recv(self):
        return json.dumps(await self.inbox.get())

    async def close(self):
        pass


def run_utterances(monkeypatch, on_text, utterances):
    async def go():
        sockets = iter([FakeWS(utterances)])
        async def fake_connect(url, key):
            return next(sockets)
        monkeypatch.setattr(stt_mod, "_connect", fake_connect)
        out = []
        async with CartesiaManualSTT(api_key="k", on_text=on_text) as stt:
            for u in utterances:
                for _ in u[:-1]:
                    await stt.send_audio(b"\0\0")
                    await asyncio.sleep(0)
                out.append((await stt.finalize(timeout_s=1)).text)
        return out
    return asyncio.run(go())


def test_on_text_streams_deltas_before_finalize(monkeypatch):
    seen = []
    texts = run_utterances(monkeypatch, lambda d, so_far: seen.append(so_far), [[" Cess", "na one two three", ", hold short"]])
    assert texts == ["Cessna one two three, hold short"]
    assert seen[:2] == ["Cess", "Cessna one two three"]  # before finalize was sent


def test_each_finalize_returns_only_its_own_utterance(monkeypatch):
    for on_text in (None, lambda d, s: None):
        texts = run_utterances(monkeypatch, on_text, [[" Runway", " 33."], [" Say", " again."]])
        assert texts == ["Runway 33.", "Say again."]
