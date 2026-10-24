"use strict";
// Unstep live room client. All text from people and agents is inserted as text, never as HTML.

const $ = (id) => document.getElementById(id);
const SVG = "http://www.w3.org/2000/svg";

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

function s(tag, attrs, text) {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
  if (text !== undefined) el.textContent = text;
  return el;
}

const SEAT_HELP = {
  atc: "Talk on the radio and supervise the agents. You only decide the edge cases they escalate.",
  aircraft: "Fly this aircraft: listen on the radio, hear Unstep in your left ear, read back clearances.",
  observer: "Big screen for judges: every agent, every message, every explanation, read-only.",
};
const SUGGEST = {
  atc: ["Cessna one two three, hold short runway three three.",
        "Helicopter four five six, proceed as requested.",
        "Cessna one two three, cleared for takeoff runway three three."],
  N123AB: ["Hold short runway three three, Cessna one two three.",
           "Hold short runway two three, Cessna one two three."],
  H456: ["Helicopter four five six, request transition over the field, northbound.",
         "Helicopter four five six, ready to taxi."],
};
const ASK = ["Unstep, what was my last clearance?", "Unstep, what runway was I told to stop at?"];
const NODE_POS = {
  people: [80, 210], radio: [250, 210],
  tower_stt: [440, 80], "cockpit:N123AB": [440, 210], "cockpit:H456": [440, 340],
  gateway: [620, 210],
  ground: [800, 75], policy: [800, 195], monitor: [800, 320],
  controller: [1000, 130], elastic: [1000, 320],
};
const NODE_KIND = {
  people: "human", radio: "core", tower_stt: "cartesia", "cockpit:N123AB": "moss", "cockpit:H456": "moss",
  gateway: "core", ground: "elastic", policy: "core", monitor: "moss", controller: "human", elastic: "elastic",
};
const KIND_COLOR = { cartesia: "#f59e42", moss: "#4ade80", elastic: "#60a5fa", human: "#c084fc", core: "#94a3b8" };
const EDGES = [["people", "radio"], ["radio", "tower_stt"], ["radio", "cockpit:N123AB"], ["radio", "cockpit:H456"],
  ["tower_stt", "gateway"], ["cockpit:N123AB", "gateway"], ["cockpit:H456", "gateway"], ["gateway", "ground"],
  ["gateway", "policy"], ["gateway", "monitor"], ["policy", "controller"], ["gateway", "controller"],
  ["gateway", "elastic"], ["ground", "elastic"]];
const STATUS_TEXT = {
  detected: "detected", proposed: "proposed", auto_relayed: "auto-relayed", needs_you: "needs you",
  approved: "approved", delivered: "delivered", confirmed: "confirmed", readback_wrong: "readback wrong",
  rejected: "rejected", expired: "expired",
};

const st = {
  station: null, kind: null, ws: null, offset: 0, stations: [], traces: new Map(), open: new Set(),
  audio: null, hello: null, live: false,
};

// ------------------------------------------------------------ helpers

function now() { return Date.now() + st.offset; }
function toast(text) {
  const el = $("status");
  el.textContent = text;
  el.classList.add("show");
  clearTimeout(toast.t);
  toast.t = setTimeout(() => el.classList.remove("show"), 5000);
}
function send(msg) {
  if (st.ws && st.ws.readyState === WebSocket.OPEN) st.ws.send(JSON.stringify(msg));
  else toast("Not connected yet");
}
function label(id) {
  if (id === "people") return "People";
  const n = (st.hello?.graph || []).find((x) => x.id === id);
  return n ? n.label : id;
}
function ensureAudio() {
  if (!st.audio) st.audio = new (window.AudioContext || window.webkitAudioContext)();
  if (st.audio.state === "suspended") st.audio.resume();
  return st.audio;
}
async function playWav(b64) {
  if (!b64) return;
  try {
    const ctx = ensureAudio();
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const buf = await ctx.decodeAudioData(bytes.buffer);
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(ctx.destination);
    src.start();
  } catch (e) {
    console.warn("audio", e);
  }
}
function rel(ms) {
  const d = Math.max(0, Math.round((now() - ms) / 1000));
  return d < 60 ? `${d}s ago` : `${Math.round(d / 60)}m ago`;
}

// ------------------------------------------------------------ seats

async function showJoin() {
  $("join").hidden = false;
  $("app").hidden = true;
  $("change").hidden = true;
  const render = async () => {
    let data;
    try {
      data = await (await fetch("/live/stations")).json();
    } catch {
      return;
    }
    $("mode").textContent = data.live ? "LIVE: Cartesia speech" : "offline: fake speech";
    const titles = { atc: "Control Tower (laptop)", N123AB: "Plane A · Cessna 1-2-3", H456: "Plane B · Helicopter 4-5-6" };
    $("seats").replaceChildren(...data.stations.filter((sta) => sta.kind !== "observer").map((sta) => h("button", {
      class: "seat-card",
      onclick: () => { ensureAudio(); location.hash = sta.id; start(sta.id); },
    }, h("h3", {}, titles[sta.id] || sta.label), h("p", {}, SEAT_HELP[sta.kind] || ""),
      h("div", { class: "who" }, `${data.connected[sta.id] || 0} connected`))));
  };
  await render();
  showJoin.timer = setInterval(render, 3000);
}

function start(station) {
  if (station === "atc") {
    $("tower-access").showModal();
    return;
  }
  clearInterval(showJoin.timer);
  st.station = station;
  $("join").hidden = true;
  $("app").hidden = false;
  $("change").hidden = false;
  connect();
}

function connect() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${scheme}://${location.host}/live/ws/${encodeURIComponent(st.station)}${window.UNSTEP_TOKEN_QUERY || ""}`);
  st.ws = ws;
  ws.onopen = () => { $("conn").textContent = "connected"; $("conn").className = "conn on"; };
  ws.onclose = () => {
    $("conn").textContent = "reconnecting";
    $("conn").className = "conn off";
    setTimeout(() => { if (st.ws === ws) connect(); }, 1500);
  };
  ws.onmessage = (ev) => onMessage(JSON.parse(ev.data));
}

// ------------------------------------------------------------ messages

function onMessage(m) {
  switch (m.type) {
    case "hello": return onHello(m);
    case "presence": return;
    case "onair": playWav(m.audio); return radioOnAir(m);
    case "transmitting": $("tx-note").textContent = "You are transmitting..."; return;
    case "radio": return radioCluster(m);
    case "transcript": return radioTranscript(m.transcript);
    case "flow": return animateFlow(m);
    case "trace": st.traces.set(m.trace.event_id, m.trace); return renderTraces();
    case "advisory_audio": return playWav(m.audio);
    case "cockpit_line": return cockpitLine(m);
    case "controller_audio": toast(m.text); return playWav(m.audio);
    case "insight": return addInsight(m.insight);
    case "autonomy": $("autonomy").checked = m.on; return toast(`Auto-relay ${m.on ? "on" : "off"}`);
    case "status": return toast(m.text);
    default: return;
  }
}

function onHello(m) {
  st.hello = m;
  st.offset = m.now_ms - Date.now();
  st.live = m.live;
  st.stations = m.stations;
  const me = m.stations.find((x) => x.id === m.you);
  st.kind = me.kind;
  $("seat").textContent = me.label;
  $("freq").textContent = m.frequency;
  $("mode").textContent = m.live ? "LIVE: Cartesia speech" : "offline: fake speech";
  const sup = st.kind === "atc" || st.kind === "observer";
  $("supervisor").hidden = !sup;
  $("queue-panel").hidden = !sup;
  $("events-panel").hidden = !sup;
  $("insights-panel").hidden = !sup;
  $("pilot-panel").hidden = st.kind !== "aircraft";
  $("tx-controls").hidden = st.kind === "observer";
  $("autonomy").disabled = st.kind !== "atc";
  $("autonomy").checked = m.autonomy;
  $("ptt").hidden = !(m.mic && navigator.mediaDevices && window.isSecureContext);
  $("tx-note").textContent = $("ptt").hidden
    ? "Type and press Transmit. Two people transmitting at once step on each other."
    : "Type, or hold Space / the button to talk. Two people transmitting at once step on each other.";
  $("say-chips").replaceChildren(...(SUGGEST[m.you] || []).map((t) =>
    h("button", { type: "button", onclick: () => send({ type: "say", text: t }) }, t)));
  $("ask-chips").replaceChildren(...ASK.map((t) =>
    h("button", { type: "button", onclick: () => send({ type: "ask", text: t }) }, t)));
  st.traces = new Map(m.traces.map((t) => [t.event_id, t]));
  $("radio").replaceChildren();
  m.radio.forEach(radioCluster);
  $("insights").replaceChildren(h("div", { class: "empty" },
    "No patterns yet. The monitor flags repeated blocked calls and readback errors."));
  m.insights.forEach(addInsight);
  if (sup) drawGraph();
  renderTraces();
}

// ------------------------------------------------------------ radio

function radioOnAir(m) {
  const who = m.station === "atc" ? "TOWER" : m.station;
  const el = h("div", { class: "tx", id: `air-${m.tx_id}` }, h("span", { class: "who" }, who),
    h("span", { class: "onair" }, "on air..."));
  $("radio").append(el);
  $("radio").scrollTop = $("radio").scrollHeight;
}

function radioCluster(m) {
  for (const t of m.transmissions) {
    document.querySelectorAll(".tx .onair").forEach((x) => x.closest(".tx").remove());
  }
  const blocked = m.overlaps.length > 0;
  for (const t of m.transmissions) {
    const who = t.station === "atc" ? "TOWER" : t.station;
    const mine = t.station === st.station;
    const shown = mine || st.kind !== "aircraft" ? (t.text || "(voice)") : (blocked ? "(garbled)" : (t.text || "(voice)"));
    $("radio").append(h("div", { class: `tx${blocked ? " blocked" : ""}` }, h("span", { class: "who" }, who), shown,
      blocked ? h("span", { class: "tag" }, `STEPPED ON: ${m.overlaps[0].stations.map((x) => x === "atc" ? "tower" : x).join(" + ")}`) : null));
  }
  $("tx-note").textContent = "";
  $("radio").scrollTop = $("radio").scrollHeight;
}

function radioTranscript(t) {
  if (st.kind === "aircraft") return;
  $("radio").append(h("div", { class: "tx dim small" }, h("span", { class: "who" }, "Cartesia"),
    `tower transcript: ${t.text}`));
  $("radio").scrollTop = $("radio").scrollHeight;
}

// ------------------------------------------------------------ pilot

function cockpitLine(m) {
  const text = m.text.replace(/^\[chime\]\s*/, "");
  if (m.party === "PILOT EAR") $("advisory").textContent = text;
  const lat = Object.entries(m.latency || {}).map(([k, v]) => `${k} ${Math.round(v * 10) / 10}`).join(", ");
  $("cockpit").append(h("div", { class: "line" }, h("span", { class: "p" }, m.party), text,
    lat ? h("span", { class: "dim small" }, `  [${lat}]`) : null));
  $("cockpit").scrollTop = $("cockpit").scrollHeight;
}

function addInsight(i) {
  $("insights").querySelector(".empty")?.remove();
  $("insights").prepend(h("div", { class: "line" }, h("span", { class: "p" }, i.kind), i.text));
}

// ------------------------------------------------------------ agent graph

function drawGraph() {
  const g = $("graph");
  g.replaceChildren();
  const edges = s("g", {});
  for (const [a, b] of EDGES) {
    const [x1, y1] = NODE_POS[a];
    const [x2, y2] = NODE_POS[b];
    edges.append(s("line", { x1, y1, x2, y2, class: "edge", id: `e-${a}-${b}` }));
  }
  g.append(edges);
  const ids = ["people", ...(st.hello.graph || []).map((n) => n.id)];
  for (const id of ids) {
    if (!NODE_POS[id]) continue;
    const [x, y] = NODE_POS[id];
    const n = (st.hello.graph || []).find((v) => v.id === id) || { label: "People on the radio", sub: "tower and pilots" };
    const w = id === "people" ? 140 : 170;
    const node = s("g", { class: "node", id: `n-${id}` });
    node.append(s("rect", { x: x - w / 2, y: y - 28, width: w, height: 56, stroke: KIND_COLOR[NODE_KIND[id]] }));
    node.append(s("text", { x, y: y - 4, "text-anchor": "middle" }, n.label));
    node.append(s("text", { x, y: y + 14, "text-anchor": "middle", class: "sub" }, n.sub));
    g.append(node);
  }
  g.append(s("g", { id: "pulses" }));
}

function nodeId(id) {
  if (id === "atc" || (id || "").startsWith("pilot:")) return "people";
  return id;
}

// Flows arrive in bursts; play them one after another so labels stay readable.
const flowQueue = [];
let flowBusy = false;
function animateFlow(m) {
  if (st.kind === "aircraft" || !NODE_POS[nodeId(m.from)] || !NODE_POS[nodeId(m.to)]) return;
  if (flowQueue.length > 40) flowQueue.shift();
  flowQueue.push(m);
  if (!flowBusy) nextFlow();
}
function nextFlow() {
  const m = flowQueue.shift();
  if (!m) { flowBusy = false; return; }
  flowBusy = true;
  playFlow(m);
  setTimeout(nextFlow, 140);
}
function playFlow(m) {
  const a = nodeId(m.from);
  const b = nodeId(m.to);
  const [x1, y1] = NODE_POS[a];
  const [x2, y2] = NODE_POS[b];
  const color = KIND_COLOR[NODE_KIND[a]] || "#fff";
  const layer = $("pulses");
  if (!layer) return;
  const dot = s("circle", { cx: x1, cy: y1, r: 6, fill: color });
  const quiet = m.label === "stored";  // every message is stored; a dot is enough
  const text = s("text", { x: (x1 + x2) / 2, y: (y1 + y2) / 2 - 8, "text-anchor": "middle", class: "flow-label" },
    quiet ? "" : m.label);
  layer.append(dot, text);
  const edge = $(`e-${a}-${b}`) || $(`e-${b}-${a}`);
  if (edge) edge.classList.add("hot");
  [a, b].forEach((id) => $(`n-${id}`)?.classList.add("flash"));
  const t0 = performance.now();
  const dur = 700;
  const step = (t) => {
    const p = Math.min(1, (t - t0) / dur);
    dot.setAttribute("cx", x1 + (x2 - x1) * p);
    dot.setAttribute("cy", y1 + (y2 - y1) * p);
    text.setAttribute("opacity", String(1 - p * 0.6));
    if (p < 1) requestAnimationFrame(step);
    else {
      dot.remove();
      setTimeout(() => text.remove(), 400);
      if (edge) edge.classList.remove("hot");
      [a, b].forEach((id) => $(`n-${id}`)?.classList.remove("flash"));
    }
  };
  requestAnimationFrame(step);
}

// ------------------------------------------------------------ events, queue, explanations

function towerWords(trace) {
  const t = trace.tower;
  const e = trace.event;
  if (!t) return null;
  const words = (t.words && t.words.length ? t.words : t.text.split(" ").map((w) => ({ word: w })));
  return h("div", { class: "words" }, ...words.flatMap((w) => {
    let blocked = false;
    if (e && w.start !== undefined) {
      const s0 = t.ptt_start + w.start * 1000;
      const s1 = t.ptt_start + w.end * 1000;
      const ov = Math.max(0, Math.min(s1, e.overlap_end) - Math.max(s0, e.overlap_start));
      blocked = s1 > s0 && ov * 2 >= s1 - s0;
    }
    return [blocked ? h("s", {}, w.word) : w.word, " "];
  }));
}

function evidence(trace) {
  const box = h("div", {});
  const tw = towerWords(trace);
  if (tw) box.append(h("div", { class: "small dim" }, "Tower said (struck words were stepped on)"), tw);
  if (trace.event) {
    box.append(h("div", { class: "small dim" }, `Cockpit ${trace.callsign} heard: "${trace.event.heard_text}"`));
    const hint = trace.event.local_hint;
    if (hint && hint.kind === "restrictive") {
      box.append(h("div", { class: "small dim" },
        `Moss hint "${hint.text}" from ${hint.source_doc_id} in ${hint.moss_ms} ms: "${hint.source_text || ""}"`));
    }
  }
  if (trace.policy) {
    box.append(h("table", { class: "checks" }, ...trace.policy.checks.map((c) =>
      h("tr", {}, h("td", { class: c.ok ? "ok" : "no" }, c.ok ? "pass" : "fail"), h("td", {}, c.name), h("td", { class: "dim" }, c.detail)))));
  }
  const t0 = trace.created_ms;
  box.append(h("ul", { class: "steps" }, ...trace.steps.map((step) => h("li", {},
    h("span", { class: "t" }, `+${((step.ts - t0) / 1000).toFixed(1)}s`),
    h("span", { class: "who" }, label(step.actor)),
    h("span", { class: "txt" }, step.text)))));
  return box;
}

function renderTraces() {
  if (st.kind === "aircraft" || !st.hello) return;
  const traces = [...st.traces.values()].sort((a, b) => b.created_ms - a.created_ms);
  const waiting = traces.filter((t) => t.status === "needs_you");
  $("queue-count").textContent = waiting.length;
  $("queue-count").className = `count${waiting.length ? " hot" : ""}`;
  $("queue").replaceChildren(...(waiting.length ? waiting.map(queueCard)
    : [h("div", { class: "empty" }, "Nothing needs you. The agents are relaying routine calls; edge cases appear here.")]));
  $("events").replaceChildren(...(traces.length ? traces.map((t) => {
    const d = h("details", { class: "event", open: st.open.has(t.event_id) || null },
      h("summary", {}, h("b", {}, t.callsign || "?"), h("span", { class: `chip ${t.status}` }, STATUS_TEXT[t.status] || t.status),
        h("span", { class: "instr" }, t.proposal ? t.proposal.instruction_text : "working..."),
        h("span", { class: "dim small" }, rel(t.created_ms))),
      evidence(t));
    d.addEventListener("toggle", () => (d.open ? st.open.add(t.event_id) : st.open.delete(t.event_id)));
    return d;
  }) : [h("div", { class: "empty" }, "No blocked calls yet. Ask two people to transmit at the same time.")]));
}

function queueCard(t) {
  const p = t.proposal || {};
  const bar = h("div", {});
  const card = h("div", { class: "card", "data-deadline": t.deadline_ms, "data-created": t.created_ms },
    h("h3", {}, `${t.callsign}: ${p.instruction_text || ""}`),
    towerWords(t),
    h("ul", { class: "reasons" }, ...((t.policy && t.policy.reasons) || []).map((r) => h("li", {}, r))),
    h("div", { class: "bar" }, bar),
    st.kind === "atc" ? h("div", { class: "actions" },
      h("button", { class: "good", onclick: () => send({ type: "decide", event_id: t.event_id, approve: true }) }, "Approve and send"),
      h("button", { class: "danger", onclick: () => send({ type: "decide", event_id: t.event_id, approve: false }) }, "Reject: ask to say again"))
      : h("div", { class: "dim small" }, "Waiting for the controller"));
  updateBar(card);
  return card;
}

function updateBar(card) {
  const deadline = Number(card.dataset.deadline);
  const created = Number(card.dataset.created);
  const bar = card.querySelector(".bar > div");
  if (!deadline || !bar) return;
  const left = Math.max(0, deadline - now());
  bar.style.width = `${Math.max(0, Math.min(100, (left / Math.max(1, deadline - created)) * 100))}%`;
}
setInterval(() => document.querySelectorAll(".card").forEach(updateBar), 500);

// ------------------------------------------------------------ inputs

$("say-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = $("say").value.trim();
  if (!text) return;
  ensureAudio();
  send({ type: "say", text });
  $("say").value = "";
});
$("ask-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = $("ask").value.trim();
  if (!text) return;
  send({ type: "ask", text });
  $("ask").value = "";
});
$("autonomy").addEventListener("change", (e) => send({ type: "autonomy", on: e.target.checked }));
$("change").addEventListener("click", () => { location.hash = ""; location.reload(); });

// Hold-to-talk microphone: 16 kHz mono PCM, sent when the key is released.
const mic = { stream: null, ctx: null, chunks: [], on: false, start: 0 };
async function micDown() {
  if (mic.on) return;
  try {
    if (!mic.stream) {
      mic.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      mic.ctx = new AudioContext();
      const src = mic.ctx.createMediaStreamSource(mic.stream);
      const node = mic.ctx.createScriptProcessor(4096, 1, 1);
      node.onaudioprocess = (e) => { if (mic.on) mic.chunks.push(new Float32Array(e.inputBuffer.getChannelData(0))); };
      src.connect(node);
      node.connect(mic.ctx.destination);
    }
  } catch (e) {
    toast("Microphone unavailable: use the say box");
    return;
  }
  mic.chunks = [];
  mic.start = now();
  mic.on = true;
  $("ptt").classList.add("down");
  send({ type: "key", down: true });
}
function micUp() {
  if (!mic.on) return;
  mic.on = false;
  $("ptt").classList.remove("down");
  const total = mic.chunks.reduce((n, c) => n + c.length, 0);
  if (total < mic.ctx.sampleRate * 0.3) { send({ type: "key", down: false }); return; }
  const all = new Float32Array(total);
  let o = 0;
  for (const c of mic.chunks) { all.set(c, o); o += c.length; }
  const ratio = mic.ctx.sampleRate / 16000;
  const out = new Int16Array(Math.floor(all.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const a = Math.floor(i * ratio);
    const b = Math.min(all.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = a; j < b; j++) sum += all[j];
    out[i] = Math.max(-1, Math.min(1, sum / Math.max(1, b - a))) * 32767;
  }
  const bytes = new Uint8Array(out.buffer);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  send({ type: "mic", pcm: btoa(bin), start_ms: Math.round(mic.start) });
}
$("ptt").addEventListener("pointerdown", (e) => { e.preventDefault(); micDown(); });
$("ptt").addEventListener("pointerup", micUp);
$("ptt").addEventListener("pointerleave", micUp);
document.addEventListener("keydown", (e) => {
  if (e.code === "Space" && !e.repeat && !$("ptt").hidden && document.activeElement?.tagName !== "INPUT") {
    e.preventDefault();
    micDown();
  }
});
document.addEventListener("keyup", (e) => { if (e.code === "Space") micUp(); });

// ------------------------------------------------------------ boot

$("tower-access-form").addEventListener("submit", (event) => {
  event.preventDefault();
  try { sessionStorage.setItem("unstep-atc-password", $("tower-password").value); } catch { /* Console asks again. */ }
  $("tower-password").value = "";
  location.href = "/live/atc/";
});
$("tower-cancel").addEventListener("click", () => {
  $("tower-access").close(); location.hash = "";
  if ($("join").hidden) showJoin();
});
$("projector-seat").addEventListener("click", () => { ensureAudio(); start("observer"); });

const seat = decodeURIComponent(location.hash.slice(1));
if (seat) start(seat);
else showJoin();
