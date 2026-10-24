"""Pre-flight check before presenting: run this at the judging table.

Checks keys, the demo clips, the presenter port, Cartesia TTS and STT, Moss,
Moss Inference and Elastic, and plays a short test tone so you can check the
speaker. Prints one line per check and exits 1 if anything needed for the live
demo is missing. It makes a few small API calls (one TTS line, one STT clip,
one Moss query, one Moss Inference answer); nothing is written to Moss.

Run: python scripts/preflight.py [--port 8765] [--no-sound]
"""

import argparse
import asyncio
import os
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

CLIPS = ["clean_call.wav", "stepped_on_call.wav", "controller_approve.wav", "wrong_readback.wav",
         "correct_readback.wav", "pilot_question.wav", "pilot_question_stop.wav"]
results: list[tuple[str, bool, str, bool]] = []  # name, ok, detail, required


def check(name: str, ok: bool, detail: str = "", required: bool = True) -> None:
    results.append((name, ok, detail, required))
    mark = "OK  " if ok else ("FAIL" if required else "WARN")
    print(f"[{mark}] {name}" + (f": {detail}" if detail else ""))


def port_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


async def cartesia() -> None:
    import numpy as np

    from unstep.cockpit.audio import read_wav
    from unstep.cockpit.stt import CartesiaManualSTT
    from unstep.cockpit.tts import CartesiaTTS

    tts = None
    try:
        tts = CartesiaTTS()  # raises if CARTESIA_VOICE_ID is missing; report it, don't crash
        first = []
        t = time.perf_counter()
        r = await tts.speak("Unstep pre-flight check.", on_chunk=lambda c: first.append(time.perf_counter() - t) if not first else None)
        check("Cartesia TTS", bool(r.pcm), f"first audio {first[0] * 1000:.0f} ms" if first else "no audio")
    except Exception as e:
        check("Cartesia TTS", False, f"{type(e).__name__}: {e}"[:160])
    finally:
        if tts is not None:
            await tts.close()
    try:
        pcm = (np.clip(read_wav(ROOT / "assets/clips/real/controller_approve.wav"), -1, 1) * 32767).astype("<i2").tobytes()
        async with CartesiaManualSTT() as stt:
            for i in range(0, len(pcm), 3200):
                await stt.send_audio(pcm[i:i + 3200])
                await asyncio.sleep(0.1)
            t = time.perf_counter()
            text = (await stt.finalize()).text
        check("Cartesia STT", "approve" in text.lower(), f"heard {text.strip()!r} in {(time.perf_counter() - t) * 1000:.0f} ms")
    except Exception as e:
        check("Cartesia STT", False, f"{type(e).__name__}: {e}"[:160])


async def moss() -> None:
    from moss import MossClient, QueryOptions

    try:
        client = MossClient(os.environ["MOSS_PROJECT_ID"], os.environ["MOSS_PROJECT_KEY"])
        names = {i.name for i in await client.list_indexes()}
        check("Moss indexes", {"airport-KUNS", "flight-N123AB"} <= names, ", ".join(sorted(names)))
        session = await client.session(index_name="airport-KUNS")
        r = await session.query("hold short runway", QueryOptions(top_k=1))
        check("Moss search", bool(r.docs), f"{r.time_taken_ms} ms")
    except Exception as e:
        check("Moss", False, f"{type(e).__name__}: {e}"[:160])
    try:
        from unstep.cockpit.inference import create_answerer
        from unstep.cockpit.memory import Doc

        answerer = create_answerer()
        t = time.perf_counter()
        a = await answerer.answer("Which runway?", [Doc(id="pf", text="Cessna 1-2-3, hold short Runway 33", metadata={})])
        check("Moss Inference", bool(a.text), f"{(time.perf_counter() - t) * 1000:.0f} ms, answered {a.text[:50]!r}",
              required=False)
    except Exception as e:
        check("Moss Inference", False, f"{type(e).__name__}: {e}"[:160], required=False)


async def elastic() -> None:
    from unstep.config import elastic_settings

    settings = elastic_settings()
    if settings is None:
        check("Elastic", False, "not configured; analytics card will use gateway counts", required=False)
        return
    import httpx

    url, key = settings
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(url.rstrip("/"), headers={"Authorization": f"ApiKey {key}"})
        check("Elastic", r.status_code == 200, f"HTTP {r.status_code}", required=False)
    except Exception as e:
        check("Elastic", False, f"{type(e).__name__}", required=False)


def sound() -> None:
    try:
        import numpy as np
        import sounddevice as sd

        t = np.arange(int(0.4 * 24000)) / 24000
        tone = (0.2 * np.sin(2 * np.pi * 880 * t)).astype(np.float32)
        stereo = np.column_stack([tone, np.zeros_like(tone)])
        sd.play(stereo, 24000)
        sd.wait()
        check("Speaker", True, "played a short tone in the LEFT channel; did you hear it?", required=False)
    except Exception as e:
        check("Speaker", False, f"{type(e).__name__}", required=False)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-sound", action="store_true")
    args = p.parse_args()

    for key in ("CARTESIA_API_KEY", "CARTESIA_VOICE_ID", "MOSS_PROJECT_ID", "MOSS_PROJECT_KEY"):
        check(f"{key} set", bool(os.getenv(key)))
    check("CARTESIA_PRONUNCIATION_DICT_ID set", bool(os.getenv("CARTESIA_PRONUNCIATION_DICT_ID")), required=False)
    missing = [c for c in CLIPS if not (ROOT / "assets/clips/real" / c).is_file()]
    check("Demo clips", not missing, "missing: " + ", ".join(missing) if missing else f"{len(CLIPS)} present")
    check(f"Port {args.port} free", port_free(args.port), "" if port_free(args.port) else "presenter already running?")
    video = ROOT / "data/video/unstep-demo-live.mp4"
    check("Backup video", video.is_file(), str(video) if video.is_file() else "run scripts/record_demo_video.py", required=False)

    async def services():
        await asyncio.gather(cartesia(), moss(), elastic())

    asyncio.run(services())
    if not args.no_sound:
        sound()

    failed = [n for n, ok, _, req in results if req and not ok]
    print("\nREADY: python -m unstep.demo --live" if not failed else f"\nNOT READY: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
