# Demo clips

Synthetic placeholders made by `python scripts/make_demo_clips.py`. They are not
real speech: "speech" is band-limited noise under syllable envelopes, and the
stepped-on call adds a heterodyne beat tone plus static from 1.3 s to 2.6 s.
They exist to exercise the squelch and overlap detector until real recorded or
Cartesia-generated audio replaces them. STT is tested separately.

| File | What |
| --- | --- |
| `clean_call.wav` | Tower call, ~2.6 s, no overlap |
| `stepped_on_call.wav` | Same call, second carrier overlaps 1.3 s to 2.6 s |
| `wrong_readback.wav` | Pilot readback placeholder (wrong) |
| `correct_readback.wav` | Pilot readback placeholder (correct) |
