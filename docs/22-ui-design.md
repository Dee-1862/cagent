# UI Design: A 3D Airport You Can Fly Into

The overhaul of both screens: the **ATC view** on the projector and the **plane view** on each phone. The idea is a live simulation. A 3D airport sits at the centre of the projector, and **when you scan the QR code, your plane appears at the airport.** Everything else is quiet, clean and Apple-like, so a judge understands it in ten seconds.

| Field | Value |
| --- | --- |
| Status | Draft v1.0, the spec Codex builds from |
| Last updated | 2026-10-24 |
| ATC view owner | Rishit's side (`web/live/atc/`) |
| Plane view owner | Deekshith's side (`app/`); this spec is a proposal to them |

---

## 1. What we looked at, and what we take from each

| Reference | What it does well | What we take |
| --- | --- | --- |
| **Apple Human Interface Guidelines**: clarity, deference, depth ([HIG summary](https://www.superdesign.dev/blog/apple-design-system), [Materials](https://glama.ai/mcp/servers/@tmaasen/apple-dev-mcp/blob/b82f0efe2115dc4539c83a2374a714a84aeb350a/content/universal/materials.md)) | The interface never competes with the content. Legible type, precise icons, minimal ornament | The 3D airport *is* the content; panels defer to it |
| **Apple Liquid Glass** (iOS 26) | Controls float on a translucent glass layer above content, and never inside content | Floating glass panels over the 3D scene, for controls and status only |
| **Liquid Glass criticism** ([prototypr](https://blog.prototypr.io/why-apples-liquid-glass-design-is-a-step-backward-for-ux-5db4652c2a4c), [morrick.me](https://morrick.me/archives/10068)) | When everything is see-through, the eye fights noise; extra padding hides information | Glass only behind controls, with strong blur and a dark tint so text stays readable. Never glass over glass. Keep density reasonable |
| **Flightradar24 3D view** ([FR24 blog](https://www.flightradar24.com/blog/inside-flightradar24/introducing-enhanced-3d-view-on-flightradar24/), [Cesium](https://cesium.com/blog/2020/08/13/flightradar24/)) | Real aircraft models in a 3D scene, a soft sun shadow, one info panel for the selected flight, settings tucked away | Real downloaded models, soft shadows, one detail card for the selected plane, no clutter |
| **Flighty** (airline-passenger app; [review](https://ipadpilotnews.com/?p=23008)) | One status per flight, readable at a glance; Live Activities on the lock screen | The phone shows one big status at a time, like a Live Activity |
| **Codrops "The Aviator"** (three.js; [tutorial](https://tympanus.net/codrops/2016/04/26/the-aviator-animating-basic-3d-scene-threejs)) | A friendly, stylized 3D scene with soft lighting and gentle motion | A stylized, low-poly airport, not photoreal; gentle idle motion |
| **2025 Apple Design Award, Visuals and Graphics** ([winners](https://www.apple.com/sn/newsroom/2025/06/apple-unveils-winners-and-finalists-of-the-2025-apple-design-awards)) | Polish comes from restraint, motion and one strong visual idea | One strong idea (the airport), restrained everything else |

**Principles we commit to:**
1. **The airport is the hero.** At least 60% of the projector is the 3D scene.
2. **Defer.** Panels are small, floating glass. Nothing permanent covers the runway.
3. **One thing at a time.** A single "What just happened" line; one card for the selected plane; one card when a decision is needed.
4. **Colour means state, never decoration.** Neutral greys everywhere; colour only for status.
5. **Motion explains.** Things move only to show cause and effect: a plane appears, a call travels, a call collides.
6. **Plain English first.** No jargon without a translation ("Hold short = stop before the runway").
7. **Glanceable from the back of the room.** Big type for state, small type for evidence.

---

## 2. Design language

**Colour (dark, like a control room at night):**

| Token | Value | Use |
| --- | --- | --- |
| `--bg` | `#0B0D10` | page; scene sky fades into it |
| `--ground` | `#14181D` | airport ground plane |
| `--glass` | `rgba(22,26,32,0.62)` + `backdrop-filter: blur(24px) saturate(140%)` | floating panels |
| `--hairline` | `rgba(255,255,255,0.08)` | 1 px borders inside glass |
| `--text` | `#F5F7FA` | primary text |
| `--text-2` | `#9BA4AF` | secondary text |
| `--blue` | `#0A84FF` (Apple system blue, dark) | tower, links, "transmitting" |
| `--green` | `#30D158` | done, read back correctly |
| `--amber` | `#FFD60A` | needs a decision, "hold short" line on the ground |
| `--red` | `#FF453A` | talked over, wrong readback |
| `--violet` | `#BF5AF2` | private advisory (only you can hear this) |

**Type:** the system stack `-apple-system, BlinkMacSystemFont, "SF Pro Display", "Inter", system-ui, sans-serif`. Inter (Google Fonts) is the fallback off Apple devices.

| Style | Size / weight | Use |
| --- | --- | --- |
| Large title | 40 / 700, tracking −0.02em | "What just happened" on the projector |
| Title | 22 / 600 | card titles, plane names |
| Body | 17 / 400 | sentences |
| Caption | 13 / 500, `--text-2` | evidence, timings, sponsor chips |
| Mono | `ui-monospace, "SF Mono"` 13 | ms numbers only |

**Shape and space:** an 8-point grid. Panels have radius 20 and 24 px padding; chips radius 999; buttons 44 px minimum height (Apple's touch target). Shadows: one soft shadow under glass (`0 20px 60px rgba(0,0,0,0.45)`), never stacked.

**Icons:** simple line icons drawn as inline SVG, 1.75 px stroke (SF Symbols style). No emoji in the UI.

**Motion:** 250 ms ease-out for panels; 600 ms spring for a plane spawning; radio "pulses" travel at a steady pace. Respect `prefers-reduced-motion` (no camera moves, no pulses, instant state changes).

---

## 3. The ATC view (projector, laptop)

### 3.1 Layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│ UNSTEP   Control Tower · KUNS 118.700        ● LIVE    [QR] Scan to fly  │  ← thin glass top bar
│                                                                          │
│   What just happened                                                     │  ← large title, top-left,
│   Plane B talked over the tower. Plane A missed "hold short runway 33".  │    floating over the scene
│                                                                          │
│                 ╔════════════ 3D AIRPORT (full bleed) ═══════════╗       │
│                 ║   runway 33/15, taxiway B, hold-short line,    ║       │
│                 ║   tower, planes with name tags, radio pulses   ║  ┌────┴──────────┐
│                 ║                                                ║  │ Agents at work│ ← glass panel,
│                 ║                                                ║  │ ⚠ needs you   │   right side,
│                 ║                                                ║  │ ✓ ✓ ✓ feed    │   380 px
│                 ╚════════════════════════════════════════════════╝  └────┬──────────┘
│ ┌ Radio ─────────────────────────────────────────────┐ ┌ Safety ─┐       │
│ │ Tower   "Cessna 1-2-3, hold short runway 33"        │ │ 1  0  0 │       │  ← bottom glass strip
│ │ Plane B "request transition…"        TALKED OVER   │ └─────────┘       │
│ └────────────────────────────────────────────────────┘                   │
└──────────────────────────────────────────────────────────────────────────┘
```

- **The scene is full-bleed** behind everything. Panels float over it.
- **Top bar:** brand, airport and frequency, LIVE badge, and the QR code with "Scan to fly". The QR is big enough to scan from 3 m (at least 160 px).
- **"What just happened":** top-left, large title, one sentence, updated on every event.
- **Right panel, "Agents at work":** decision cards (amber) on top, then the feed. It is the only tall panel.
- **Bottom strip:** radio lanes (live captions) on the left, three safety numbers on the right.
- **Hidden until asked:** the full explanation steps and timing waterfall live in a sheet that slides up when you click a plane or a feed row ("Show how Unstep handled it"). The evidence is one click away, not on screen all the time.

### 3.2 The 3D airport (three.js)

- **Scene:** stylized, low-poly, matte; dark ground; runway 33/15 as a long dark-grey strip with white centreline dashes and big painted numbers "33" and "15" readable from the default camera; taxiway B joining it; an **amber hold-short line** where the taxiway meets the runway; a simple tower (box and cylinder) with a soft blue glowing cab; a few apron stands where spawned planes park.
- **Camera:** a calm three-quarter view (about 35° pitch) framing runway, taxiway and tower. Very slow idle orbit (one turn in about 4 minutes; off with reduced motion). OrbitControls with limits, so the presenter can drag to look around; double-click resets.
- **Lighting:** a hemisphere light plus one directional "sun" with **soft shadows** (FR24's touch). Subtle fog fading into `--bg`.
- **Models (downloaded, not built; CC-BY 3.0 from Poly Pizza, see `web/live/atc/models/CREDITS.md`):**

| Aircraft | Model file |
| --- | --- |
| Cessna-type callsigns ("Cessna 1-2-3") | `small-plane.glb` |
| Helicopter callsigns ("Helicopter 4-5-6") | `helicopter.glb` |
| Jet callsigns | `jet.glb` |
| Airliner callsigns | `airliner-747.glb` |
| Walk-up planes | rotate through the models |

  Scale and normalise every model at load: fit to the same wingspan, centre on the ground, face along the taxiway.
- **Name tags:** a small floating glass label above each plane (HTML overlay positioned from 3D coordinates). It shows the friendly name ("Plane A · Cessna 1-2-3") and a status dot.

### 3.3 What happens in the scene (cause and effect)

| Event (existing message) | What the scene does |
| --- | --- |
| A phone joins (`stations` / `presence`) | **The plane spawns**: drops onto its stand with a soft spring and a brief ring of light on the ground; its name tag fades in; the feed says "Plane C joined" |
| Someone keys the mic (`keyed`) | A soft **blue pulse ring** expands from the speaker (tower or plane), repeating while keyed; the tag shows "ON AIR" |
| Two keys overlap (`stepon_live`) | The two pulses turn **red** where they meet; a short "TALKED OVER" tag pops over the missed plane; the plane's ring turns red |
| Advisory delivered to a plane | A thin **violet beam** from the tower to that plane, with the plane's tag "Heard privately" |
| Readback correct | Green check on the tag; the plane's ring turns green for 3 s |
| Hold short | The amber hold-short line glows while a "hold short" instruction is active for a plane |
| Seat freed / room reset | The plane fades out and lifts away |
| Decision needed | The plane's tag turns amber and gently bobs; clicking it opens the decision card |

The planes don't fly real routes; positions are illustrative (keep the existing "positions are not live tracking" note as a caption).

### 3.4 Panels

- **Agents at work** (keep all current behaviour): decision cards stay the existing ones, restyled as glass cards with the two buttons "Approve and send" (filled blue) and "Reject" (plain). Feed rows: icon (✓ green, ⚠ amber, ! red), agent name, one sentence, and a sponsor chip (Cartesia / Moss / Elastic) in caption style.
- **Radio:** one row per station, with name, live caption (keywords coloured: callsign blue, action amber, runway pink-red) and a thin level bar. "TALKED OVER" is a small red capsule.
- **Safety:** three big numbers with labels; source caption ("Elastic ES|QL · 1.2 s"); the "Simulated traffic" badge when present.
- **Evidence sheet** (slides up): the numbered steps and the timing waterfall exactly as today, restyled.
- **Footer:** one caption line with mode and credits ("3D models: Vojtěch Balák, Poly by Google, Miha Lunar · CC-BY 3.0").

---

## 4. The plane view (phone, pilot app)

The phone is **your cockpit**. Same design language; one thing on screen at a time.

```
┌──────────────────────────┐
│ ● LIVE      118.700      │  ← tiny status bar
│                          │
│  You are Plane A         │  ← large title
│  Cessna 1-2-3            │
│ ┌──────────────────────┐ │
│ │   3D: your plane at  │ │  ← small 3D "you are here" view: your plane,
│ │   the airport        │ │    close chase camera, runway behind
│ └──────────────────────┘ │
│ ┌──────────────────────┐ │
│ │ ONLY YOU CAN HEAR    │ │  ← one Live-Activity-style card, the current state:
│ │ Hold short runway 33 │ │    advisory (violet), talked over (red),
│ │ Read it back         │ │    read back ✓ (green), or live caption
│ └──────────────────────┘ │
│                          │
│        ( HOLD TO )       │  ← big round button, 120 px, bottom third
│        (  TALK   )       │    turns into a waveform while held
│   More ▾                 │
└──────────────────────────┘
```

- **Spawn moment:** right after scanning, the phone shows a 1.5 s intro. The camera swoops down to *your* plane appearing on its stand ("You are Plane A"), and at the same moment the same plane spawns on the projector. That's the magic moment: you scan, you're in the airport.
- **3D view:** the same scene and models as the ATC view, a close chase camera behind your plane, low detail on phones (no shadows, lower pixel ratio). Optional: hidden when the mic is held, to save battery.
- **One status card** (like an iOS Live Activity) shows only the newest state. The colours match the ATC view.
- **Hold to talk:** one large circular button. Held: it becomes a live waveform; red bars if someone else is talking.
- **"More":** tap-to-say lines, Ask Unstep, timings (everything that exists today, tucked away).
- **Accessibility:** 44 px targets, Dynamic-Type-like scaling, all states also spoken or vibrated (the existing earcons).

**Shared code:** the 3D scene lives in one framework-free module (`web/live/atc/scene3d.js`) with a tiny API (section 5). The pilot app can import a copy, so both screens show the same airport.

---

## 5. Implementation notes (for the build)

- **three.js r160, vendored locally** in `web/live/atc/vendor/` (no CDN at the venue), loaded with an import map:
  - `"three": "/live/static/atc/vendor/three.module.js"`
  - `"three/addons/": "/live/static/atc/vendor/addons/"`
  - Addons used: `GLTFLoader`, `OrbitControls`.
- **New `scene3d.js`** exports `createAirport(container, {quality: "high" | "low", followStation?: string})`, returning an object with:
  - `setStations(list)`: spawns and removes planes;
  - `keyed(stationIds)`, `steppedOn(stationIds)`, `advisory(stationId)`, `readback(stationId, ok)`, `holdShort(stationId, on)`, `needsYou(stationId, on)`;
  - `onSelect(callback)`: click a plane;
  - `project(stationId)`: screen position for HTML name tags;
  - `dispose()`.
- **`atc.js` keeps every existing message handler and DOM id** that tests use. The scene is driven *from* those handlers; nothing is removed from the logic. Missing WebGL falls back to the current 2D SVG map.
- **Performance:** `renderer.setPixelRatio(Math.min(devicePixelRatio, 2))`; shadows only in high quality; pause rendering when the tab is hidden.
- **Credits:** the footer line, plus `models/CREDITS.md`.

Sources: [Apple design system summary](https://www.superdesign.dev/blog/apple-design-system), [HIG Materials mirror](https://glama.ai/mcp/servers/@tmaasen/apple-dev-mcp/blob/b82f0efe2115dc4539c83a2374a714a84aeb350a/content/universal/materials.md), [Liquid Glass critique](https://blog.prototypr.io/why-apples-liquid-glass-design-is-a-step-backward-for-ux-5db4652c2a4c), [More notes on Liquid Glass](https://morrick.me/archives/10068), [Flightradar24 enhanced 3D](https://www.flightradar24.com/blog/inside-flightradar24/introducing-enhanced-3d-view-on-flightradar24/), [Cesium × Flightradar24](https://cesium.com/blog/2020/08/13/flightradar24/), [Flight tracking app review](https://ipadpilotnews.com/?p=23008), [Codrops The Aviator](https://tympanus.net/codrops/2016/04/26/the-aviator-animating-basic-3d-scene-threejs), [2025 Apple Design Awards](https://www.apple.com/sn/newsroom/2025/06/apple-unveils-winners-and-finalists-of-the-2025-apple-design-awards), [Poly Pizza](https://poly.pizza).
