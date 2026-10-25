// Unstep tower console. Only received evidence changes the aircraft states.
let airport = null;
const sceneCall = (method, ...args) => { try { airport?.[method](...args); } catch (error) { console.warn("Airport scene", error); } };
const showEvidence = (on = true) => {
  $("evidence-sheet").classList.toggle("open", on);
  $("show-evidence").setAttribute("aria-expanded", String(on));
};
function syncScene() {
  sceneCall("setStations", visibleAircraft());
  sceneCall("keyed", state.keyed);
  const latest = tracesNewestFirst();
  for (const station of visibleAircraft()) {
    const trace = latest.find((t) => t.callsign === station.id);
    sceneCall("needsYou", station.id, trace?.status === "needs_you");
    sceneCall("holdShort", station.id, !!trace && ["delivered", "readback_wrong", "needs_you"].includes(trace.status) && /hold short|hold position|stop/i.test(trace.decision?.instruction_text || trace.proposal?.instruction_text || ""));
  }
  renderPlaneTags();
}
function renderPlaneTags() {
  if (!airport) return;
  const tags = $("plane-tags");
  const ids = new Set(visibleAircraft().map((s) => s.id));
  tags.querySelectorAll("[data-station]").forEach((tag) => { if (!ids.has(tag.dataset.station)) tag.remove(); });
  for (const station of visibleAircraft()) {
    let tag = [...tags.children].find((node) => node.dataset.station === station.id);
    if (!tag) { tag = el("button", undefined, "plane-tag"); tag.dataset.station = station.id; tag.addEventListener("click", () => showEvidence()); tags.append(tag); }
    const trace = tracesNewestFirst().find((t) => t.callsign === station.id);
    tag.textContent = `${station.name || station.id} · ${station.spoken || station.callsign || station.id}${station.id in state.keyed ? " · ON AIR" : trace?.status === "needs_you" ? " · NEEDS YOU" : trace?.status === "confirmed" ? " · ✓" : ""}`;
    tag.dataset.status = trace?.status || (station.id in state.keyed ? "keyed" : "");
    try { const p = airport.project(station.id); tag.hidden = !p?.visible; if (p) { tag.style.left = `${p.x}px`; tag.style.top = `${p.y}px`; tag.style.opacity = p.opacity; } } catch { tag.hidden = true; }
  }
}
async function startAirport() {
  try {
    if (!document.createElement("canvas").getContext("webgl2") && !document.createElement("canvas").getContext("webgl")) return;
    const {createAirport} = await import("./scene3d.js");
    airport = createAirport($("scene3d"), {quality:(matchMedia("(max-width: 700px)").matches || new URLSearchParams(location.search).get("quality") === "low") ? "low" : "high"});
    window.unstepAirport = airport;  // read-only handle for tests (inspect())
    airport.onSelect(() => showEvidence());
    document.body.classList.add("has-scene");
    syncScene();
    (function tickTags() { if (!airport) return; renderPlaneTags(); requestAnimationFrame(tickTags); })();
  } catch (error) { console.warn("3D airport unavailable; using map", error); }
}
const $ = (id) => document.getElementById(id);
// Optional chrome is isolated from the radio and evidence handlers.
try {
  const side = $("side-panel"), collapse = document.querySelector(".side-collapse");
  collapse?.addEventListener("click", () => { const closed=side.classList.toggle("collapsed"); collapse.setAttribute("aria-expanded",String(!closed)); });
  document.querySelectorAll("[data-view]").forEach(button=>button.addEventListener("click",()=>{
    sceneCall("setView",button.dataset.view);
    document.querySelectorAll("[data-view]").forEach(b=>b.setAttribute("aria-pressed",String(b===button)));
    $("view-mode").textContent="3D";$("view-mode").setAttribute("aria-pressed","false");
  }));
  $("view-mode")?.addEventListener("click",event=>{const top=event.currentTarget.getAttribute("aria-pressed")!=="true";event.currentTarget.setAttribute("aria-pressed",String(top));event.currentTarget.textContent=top?"2D":"3D";sceneCall("setView",top?"top":"overview");});
  $("auto-sway")?.addEventListener("click",event=>{const on=event.currentTarget.getAttribute("aria-pressed")!=="true";event.currentTarget.setAttribute("aria-pressed",String(on));sceneCall("setAutoSway",on);});
  $("labels-toggle")?.addEventListener("click",event=>{const on=event.currentTarget.getAttribute("aria-pressed")!=="true";event.currentTarget.setAttribute("aria-pressed",String(on));$("plane-tags").classList.toggle("tags-hidden",!on);});
  const updateTime=()=>{const node=$("local-time");if(node)node.textContent=new Intl.DateTimeFormat(undefined,{hour:"2-digit",minute:"2-digit"}).format(new Date());};updateTime();setInterval(updateTime,60000);
} catch(error) { console.warn("Console chrome",error); }
const names = {atc: "Tower"};
const shortName = (id) => state.stations.get(id)?.name || (id === "atc" ? "Tower" : id || "A plane");
const state = {ws: null, ready: false, offset: 0, live: false, autonomy: false,
  stations: new Map(), connected: {}, keyed: {}, liveOverlap: new Map(), reports: new Map(), captions: new Map(), recoveries: new Map(), actions: new Map(), traces: new Map(), lanes: new Map(), pending: new Set(), audio: null, password: null, reasons: {}};
const now = () => Date.now() + state.offset;
function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
// Evidence sheet controls (after $ and el exist; at the top they threw before the console loaded).
$("show-evidence").addEventListener("click", () => showEvidence(!$("evidence-sheet").classList.contains("open")));
$("close-evidence").addEventListener("click", () => showEvidence(false));
$("feed").addEventListener("click", (event) => { if (event.target.closest(".feed-row")) showEvidence(); });
function selectTab(name) {
  if (!document.querySelectorAll) return;
  document.querySelectorAll(".side-tabs [data-tab]").forEach((button) => button.setAttribute("aria-selected", String(button.dataset.tab === name)));
  document.querySelectorAll(".tab-pane").forEach((pane) => { pane.hidden = pane.dataset.pane !== name; });
}
// Tabs and the Ask pane are layout only: if the page can't set them up, the console still works.
try {
  document.querySelectorAll(".side-tabs [data-tab]").forEach((button) => button.addEventListener("click", () => selectTab(button.dataset.tab)));
  const askPane = document.querySelector('[data-pane="ask"]');
  const moveAudit = () => {
    const audit = document.querySelector("section.panel.audit");
    if (audit && askPane && audit.parentElement !== askPane) askPane.append(audit);
  };
  new MutationObserver(moveAudit).observe(document.body, {childList:true, subtree:true});
  moveAudit();
} catch (error) { console.warn("Side panel tabs", error); }
function notice(text) { $("notice").textContent = text; }
function send(message) {
  if (!state.ready || state.ws?.readyState !== WebSocket.OPEN) { notice("Connection lost. Nothing was sent."); return false; }
  state.ws.send(JSON.stringify(message));
  return true;
}
function controls() {
  $("autonomy").disabled = !state.ready;
  $("transmit").disabled = !state.ready;
  $("reset").disabled = !state.ready;
  document.querySelectorAll("[data-say]").forEach((b) => { b.disabled = !state.ready; });
  updateCountdowns();
}

// Authentication: a one-use handoff from the picker, then memory only.
try {
  state.password = sessionStorage.getItem("unstep-atc-password");
  sessionStorage.removeItem("unstep-atc-password");
} catch { /* Direct navigation still works through the password dialog. */ }
function authenticate() {
  if (state.password !== null) state.ws.send(JSON.stringify({type: "auth", password: state.password}));
  else if (!$("auth").open) $("auth").showModal();
}
$("auth-form").addEventListener("submit", (event) => {
  event.preventDefault();
  state.password = $("password").value;
  $("password").value = "";
  $("auth").close();
  if (state.ws?.readyState === WebSocket.OPEN) authenticate();
  else connect();
});
function connect() {
  state.ready = false;
  controls();
  // On Vercel the page is a proxy of the hub's and a proxy cannot carry a WebSocket: connect straight to the hub.
  const hubHost = location.hostname.endsWith(".vercel.app") && window.UNSTEP_HUB_HOST && !window.UNSTEP_HUB_HOST.startsWith("__") ? window.UNSTEP_HUB_HOST : location.host;
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${hubHost}/live/ws/atc${window.UNSTEP_TOKEN_QUERY || ""}`);
  state.ws = ws;
  ws.onmessage = ({data}) => receive(JSON.parse(data));
  ws.onclose = (event) => {
    state.ready = false;
    state.pending.clear();
    state.keyed = {}; state.liveOverlap.clear(); renderMap(); renderRadio();
    $("connection").textContent = "OFFLINE";
    $("connection").className = "connection";
    controls();
    if (event.code === 4003) {
      state.password = null;
      $("auth-note").textContent = event.reason || "Tower access denied. Check your password and room access token.";
      if (!$("auth").open) $("auth").showModal();
    } else {
      notice("Disconnected. Showing the last received evidence; decisions are disabled. Reconnecting…");
      setTimeout(() => { if (state.ws === ws) connect(); }, 1500);
    }
  };
}

// Protocol shared with the existing plane and observer seats.
function receive(message) {
  switch (message.type) {
    case "auth_required": authenticate(); break;
    case "auth_status":
      $("password-state").textContent = message.password_set ? "Tower access protected" : "ATC password not set";
      break;
    case "hello":
      state.ready = true;
      state.offset = message.now_ms - Date.now();
      state.live = message.live;
      state.autonomy = message.autonomy;
      state.pending.clear();
      state.traces = new Map(message.traces.map((trace) => [trace.event_id, trace]));
      state.lanes.clear();
      state.keyed = message.keyed || {}; state.liveOverlap.clear();
      state.connected = {}; setStations(message.stations);
      $("frequency").textContent = message.frequency;
      $("connection").textContent = message.live ? "LIVE" : "OFFLINE · fake speech";
      $("connection").className = "connection online";
      $("mode").textContent = message.live ? "Live room · speech services configured for live mode" : "Offline demo · fake speech";
      $("autonomy").checked = state.autonomy;
      message.radio.forEach((radio) => radioEvent(radio, false));
      renderTraces(); renderRadio(); controls();
      if (!message.traces.length) $("happened").textContent = message.radio.length ? radioSentence(message.radio.at(-1)) : "Waiting for the first radio call.";
      notice(message.insights?.at(-1)?.text || "Connected. Tower decisions are ready.");
      break;
    case "stations": setStations(message.stations); renderTraces(); renderRadio(); break;
    case "presence":
      state.connected = message.connected;
      renderMap(); renderRadio(); break;
    case "keyed":
      state.keyed = message.keyed;
      renderMap(); renderRadio(); break;
    case "stepon_live":
      message.stations.forEach((id) => state.liveOverlap.set(id, message.since_ms));
      sceneCall("steppedOn", message.stations);
      renderMap(); renderRadio();
      $("happened").textContent = `${message.stations.map(shortName).join(" and ")} are talking at the same time. Someone will miss part of this call.`;
      break;
    case "radio": radioEvent(message); break;
    case "transcript": {
      const prior = state.lanes.get("atc");
      if (!prior || message.transcript.ptt_start >= prior.start_ms) {
        state.lanes.set("atc", {...prior, text: message.transcript.text, start_ms: message.transcript.ptt_start});
        renderRadio();
      }
      break;
    }
    case "trace":
      state.traces.set(message.trace.event_id, message.trace);
      if (message.trace.status === "delivered") {
        sceneCall("advisory", message.trace.callsign);
        obey(`evt-${message.trace.event_id}`, message.trace.callsign, message.trace.decision?.instruction_text || message.trace.proposal?.instruction_text);
      }
      if (["confirmed", "readback_wrong"].includes(message.trace.status)) sceneCall("readback", message.trace.callsign, message.trace.status === "confirmed");
      if (message.trace.status === "confirmed") readbackConfirmed(message.trace.callsign);
      if (message.trace.status !== "needs_you") state.pending.delete(message.trace.event_id);
      renderTraces(); renderRadio(); break;
    case "autonomy":
      state.autonomy = message.on;
      $("autonomy").checked = message.on;
      renderInbox(); notice(`Auto-resend is ${message.on ? "on" : "off"}.`); break;
    case "onair":
      $("onair").textContent = `${shortName(message.station)} is talking`;
      play(message.audio);
      setTimeout(() => { $("onair").textContent = "Listening on the shared radio"; }, Math.max(0, message.end_ms - now()));
      break;
    case "controller_audio": notice(message.text); play(message.audio); break;
    case "recovery":
      // C1: the controller hears who was blocked, in Unstep's voice; text stays if audio is missing.
      $("happened").textContent = message.text;
      state.recoveries.set(message.from_station, message); renderRadio(); renderFeed();
      notice(message.text); play(message.audio); break;
    case "caption": {
      // Live words from Cartesia while someone talks; a newer caption of the same transmission replaces the older.
      const prior = state.captions.get(message.station);
      if (!prior || prior.id !== message.id || message.ts >= prior.ts || message.final) {
        state.captions.set(message.station, message);
        renderRadio();
      }
      // A pilot's spoken call, transcribed live: its final text is the readback to check.
      if (message.final && message.station !== "atc" && message.source !== "tts") pilotSpoke(message.id, message.station, message.text);
      break;
    }
    case "level": {
      const bar = document.querySelector(`.lane[data-station="${CSS.escape(message.station)}"] .level i`);
      const peak = Math.max(0, ...message.rms);
      if (bar) bar.style.width = `${Math.min(100, Math.round(peak * 400))}%`;
      break;
    }
    case "agent_action": state.actions.set(message.id, message); renderFeed(); break;
    case "advisory_report": state.reports.set(message.station, message); renderRadio(); break;
    case "insight": notice(message.insight.text); break;
    case "flow":
      // Transport flow is evidence of routing, not evidence of delivery or timing.
      $("event-label").textContent = `Latest activity: ${message.label}`;
      break;
    case "room_reset":
      // Presenter reset: walk-up planes are gone; the board starts clean for the next group.
      state.traces.clear(); state.lanes.clear(); state.reports.clear(); state.captions.clear(); state.recoveries.clear(); state.actions.clear(); state.pending.clear();
      state.liveOverlap.clear(); state.keyed = {};
      setStations(message.stations);
      renderMap(); renderTraces(); renderRadio(); renderInbox();
      $("happened").textContent = "Room reset. Scan the QR code to fly a plane.";
      notice("Room reset. Walk-up planes were freed; the team planes stayed.");
      break;
    case "status": state.pending.clear(); renderInbox(); notice(message.text); break;
  }
}

function setStations(stations) {
  state.stations = new Map(stations.map((s) => [s.id, s]));
  for (const s of stations) names[s.id] = isAircraft(s) ? `${s.name || s.id} \u00b7 ${s.spoken || s.callsign || s.id}` : "Tower";
  renderMap();
  syncScene();
}
function isHelicopter(station) {
  return /helicopter|rotorcraft/i.test(station.kind || "") || /^H/i.test(station.callsign || station.id);
}
function isAircraft(station) {
  return station.kind === "aircraft" || isHelicopter(station);
}
// Fixed SVG slots reserve separate rectangles for labels and radio badges.
const groundSlots = [
  {x:565, y:190, lx:-205, ly:-65, width:240},
  {x:285, y:190, lx:-205, ly:-65, width:240},
  {x:85, y:300, lx:-65, ly:46, width:145},
  {x:240, y:300, lx:-65, ly:46, width:145},
  {x:395, y:300, lx:-65, ly:46, width:145},
  {x:550, y:300, lx:-65, ly:46, width:145},
];
const hoverSlots = Array.from({length:6}, (_, i) => ({x:750, y:30 + i * 56, lx:30, ly:-5, width:210}));
function visibleAircraft() {
  return [...state.stations.values()].filter((s) => isAircraft(s) && (state.connected[s.id] > 0 || s.id in state.keyed));
}
function svgNode(tag, attrs, text) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
  if (text !== undefined) node.textContent = text;
  return node;
}
function renderMap() {
  const aircraft = visibleAircraft().sort((a, b) =>
    Number(b.id === "N123AB" || b.callsign === "N123AB") - Number(a.id === "N123AB" || a.callsign === "N123AB") ||
    (a.name || a.id).localeCompare(b.name || b.id, undefined, {numeric:true}));
  let groundIndex = 0, hoverIndex = 0;
  $("tower-on-air").textContent = "atc" in state.keyed ? "ON AIR" : "";
  const count = [...state.stations.values()].filter((s) => isAircraft(s) && state.connected[s.id] > 0).length;
  $("planes").textContent = `${count} ${count === 1 ? "plane" : "planes"} connected`;
  $("map-title").textContent = `${count} connected aircraft at Unstep airport`;
  $("map-planes").replaceChildren(...aircraft.map((station) => {
    const helicopter = isHelicopter(station);
    const slot = helicopter ? hoverSlots[hoverIndex++] : groundSlots[groundIndex++];
    if (!slot) return svgNode("g", {});
    const id = station.id;
    const trace = tracesNewestFirst().find((t) => t.callsign === id);
    const view = trace ? presentation(trace) : {kind:"neutral", label:"Waiting for radio activity"};
    const group = svgNode("g", {id:`plane-${id}`, class:`plane ${view.kind}${id in state.keyed ? " transmitting" : ""}`, transform:`translate(${slot.x} ${slot.y})`});
    group.append(svgNode("circle", {class:"ring", r:22}), svgNode("path", {class:helicopter ? "aircraft helicopter" : "aircraft", d:helicopter ? "M-5-7Q5-12 12-3V5Q5 12-5 7ZM-5 0H-19M-19-6V6M2-7V-15M-17-15H21M-8 14H15M-4 7V14M10 7V14" : "M-16-3L-4-6L-8-18H-2L7-6L18-2V2L7 6L-2 18H-8L-4 6L-16 3Z"}));
    const label = svgNode("text", {x:slot.lx, y:slot.ly, "data-width":slot.width, class:"plane-name"}, names[id]);
    const status = svgNode("text", {x:slot.lx, y:slot.ly + 24, "data-width":slot.width, class:"state-label"}, view.label);
    group.append(label, status);
    if (id in state.keyed) group.append(svgNode("text", {x:slot.lx,y:slot.ly + 44,class:"map-on-air"}, "ON AIR"));
    return group;
  }));
  // Keep every label within its reserved slot, including long recovered instructions.
  $("map-planes").querySelectorAll(".plane-name, .state-label").forEach((label) => {
    const width = Number(label.dataset.width);
    if (label.getComputedTextLength() > width) {
      label.setAttribute("textLength", width); label.setAttribute("lengthAdjust", "spacingAndGlyphs");
    }
  });
  syncScene();
}

// Aircraft and the one-sentence explanation of the newest event.
function tracesNewestFirst() { return [...state.traces.values()].sort((a,b) => b.created_ms - a.created_ms); }
function presentation(trace) {
  const who = shortName(trace.callsign);
  const instruction = trace.decision?.instruction_text || trace.proposal?.instruction_text;
  const readback = trace.readbacks?.at(-1);
  if (trace.status === "confirmed") return {kind:"confirmed", label:"✓ Read back correctly", sentence:`${who} repeated the instruction correctly${instruction ? `: “${instruction}”` : "."}`};
  if (trace.status === "readback_wrong") return {kind:"wrong", label:`✕ Read back wrong${readback?.slots?.runway ? `: ${readback.slots.runway}` : ""}`, sentence:`${who} read back the wrong instruction: “${readback?.readback_text || "readback unavailable"}”.`};
  if (trace.status === "delivered") return {kind:"delivered", label:/hold short|hold position|stop/i.test(instruction || "") ? "Told to stop" : `Told: ${(instruction || "instruction delivered").slice(0,38)}`, sentence:`Unstep privately told ${who} “${instruction || "the approved instruction"}”; waiting for the pilot to repeat it.`};
  if (trace.status === "rejected" || trace.status === "expired") return {kind:"missed", label:"Missed a call · nothing sent", sentence:trace.status === "expired" ? `The decision for ${who} expired; nothing was sent.` : `The controller rejected the resend to ${who}; no instruction was sent.`};
  if (["approved", "auto_relayed"].includes(trace.status)) return {kind:"missed",label:"Missed a call · resend approved",sentence:`The resend to ${who} is approved; Unstep has not yet reported it delivered.`};
  return {kind:"missed",label:"Missed a call",sentence:instruction ? `${who} missed “${instruction}”${trace.status === "needs_you" ? "; the controller must decide whether to resend it." : "; Unstep is checking how to recover it."}` : `${who} missed a radio call; Unstep is checking what the tower said.`};
}
function renderTraces() {
  const traces = tracesNewestFirst();
  if (traces.length) $("happened").textContent = presentation(traces[0]).sentence;
  renderMap();
  renderInbox();
  renderFeed();
  const expanded = new Set([...$("history").querySelectorAll("details[open]")].map((d) => d.dataset.event));
  $("steps").replaceChildren(...(traces.length ? [steps(traces[0]), waterfall(traces[0])] : [el("p", "No blocked calls yet. The evidence chain will appear here.", "empty")]));
  $("history").replaceChildren(...traces.slice(1).map((trace) => {
    const detail = el("details"); detail.dataset.event = trace.event_id;
    detail.open = expanded.has(trace.event_id);
    detail.append(el("summary", `${shortName(trace.callsign)} · ${presentation(trace).label} · ${new Date(trace.created_ms).toLocaleTimeString()}`), steps(trace));
    return detail;
  }));
}

// "Agents at work": what each agent did, newest first. Green is finished work, amber needs
// the controller, red is a flag. Built from the room's existing messages plus agent_action.
function feedRows() {
  const rows = [];
  const add = (ts, agent, text, status, sponsor, kind = "agent") => { if (ts) rows.push({ts, agent, text, status, sponsor, kind}); };
  for (const t of state.traces.values()) {
    const who = shortName(t.callsign);
    const instruction = t.decision?.instruction_text || t.proposal?.instruction_text || "the instruction";
    let readbackIndex = 0;
    for (const s of t.steps || []) {
      switch (s.kind) {
        case "detected": add(s.ts, "Cockpit agent", `Noticed ${who} missed part of a call`, "done", "Cartesia"); break;
        case "moss_search": if (s.data?.top_hit_text) add(s.ts, "Cockpit agent", `Found “${s.data.top_hit_text}” in ${who}’s memory`, "done", s.data?.backend === "moss" ? "Moss" : null); break;
        case "proposed": add(s.ts, "Ground agents", `Drafted the fix “${instruction}”${s.data?.citation ? ` · ${s.data.citation}` : ""}`, "done", s.data?.citation ? "Elastic" : null); break;
        case "agents_cited": add(s.ts, "Ground agents", `Cited ${s.data?.citation || "the FAA rule"} for ${who}’s fix`, "done", "Elastic"); break;
        case "auto_relay": add(s.ts, "Policy agent", `Re-sent the tower’s own words to ${who} automatically`, "done", null); break;
        case "escalate": add(s.ts, "Policy agent", `Asked you to decide for ${who}`, t.status === "needs_you" ? "needs_you" : "done", null); break;
        case "approved": if (s.actor !== "policy") add(s.ts, "You", `Approved the fix for ${who}`, "done", null); break;
        case "rejected": add(s.ts, "You", `Rejected the fix for ${who}`, "done", null); break;
        case "delivered": add(s.ts, "Cockpit agent", `Told ${who} privately: “${instruction}”`, "done", "Cartesia"); break;
        case "readback": {
          const r = t.readbacks?.[readbackIndex++];
          if (r) add(s.ts, "Readback agent", r.match ? `${who} read it back correctly` : `Caught a wrong readback from ${who}: “${r.readback_text}”`, r.match ? "done" : "flag", "Cartesia");
          break;
        }
        case "expired": add(s.ts, "Gateway", `No decision for ${who} in time, so nothing was sent`, "flag", null); break;
      }
    }
  }
  for (const r of state.recoveries.values()) add(r.ts, "Recovery agent", `Told ${shortName(r.from_station)} its call was blocked, and told you`, "done", "Cartesia");
  // A fixed rule (timer, threshold) is labelled as a rule, never called an agent (D29).
  for (const a of state.actions.values()) add(a.ts, a.agent, a.detail ? `${a.text} · ${a.detail}` : a.text, a.status, a.sponsor, a.kind || "agent");
  return rows.sort((a, b) => b.ts - a.ts).slice(0, 14);
}
function renderFeed() {
  const rows = feedRows();
  const mark = {done: "✓", needs_you: "⚠", flag: "!"};
  $("feed").replaceChildren(...(rows.length ? rows.map((r) => {
    const item = el("li", undefined, `feed-row ${r.status}`);
    item.append(el("span", mark[r.status] || "·", "mark"), el("b", r.kind === "rule" ? `${r.agent} · rule` : r.agent, "who"), el("span", r.text));
    if (r.sponsor) item.append(el("small", r.sponsor, "chip"));
    return item;
  }) : [el("li", "Agents are listening. Their work appears here as it happens.", "feed-empty")]));
}

// Policy reasons come from one static mapping, also covered by Python tests.
function reason(trace) {
  const failed = (trace.policy?.checks || []).filter((check) => !check.ok);
  // Lead with the reason that matters most, while preserving every failed check below.
  const check = failed.find((c) => c.name === "restrictive") || failed[0];
  return state.reasons[check?.name] || "The automatic safety checks did not all pass, so a human must review this instruction.";
}
function spokenWords(text) {
  return text.replace(/\b[A-Z0-9]+\b/g, (id) => state.stations.get(id)?.spoken || id);
}

function towerWords(trace) {
  const paragraph = el("p", undefined, "words");
  const tower = trace.tower;
  const event = trace.event;
  if (tower?.words?.length && event) {
    for (const word of tower.words) {
      const lost = tower.ptt_start + word.start * 1000 < event.overlap_end && tower.ptt_start + word.end * 1000 > event.overlap_start;
      paragraph.append(el(lost ? "mark" : "span", `${spokenWords(word.word)} `));
    }
  } else {
    const text = tower?.text || trace.proposal?.instruction_text || "Original words unavailable";
    const normalize = (word) => word.toLowerCase().replace(/[^a-z0-9]/g, "");
    const lost = new Set((trace.proposal?.blocked_words || []).flatMap((word) => word.split(/\s+/)).map(normalize));
    for (const word of text.split(/(\s+)/)) {
      paragraph.append(el(normalize(word) && lost.has(normalize(word)) ? "mark" : "span", spokenWords(word)));
    }
  }
  return paragraph;
}
function renderInbox() {
  const waiting = tracesNewestFirst().filter((t) => t.status === "needs_you" && t.proposal).reverse();
  $("decision-count").textContent = waiting.length;
  if (waiting.length) selectTab("agents");
  if (!waiting.length) {
    const empty = el("div", undefined, "empty");
    empty.append(el("strong", "Nothing needs you right now."), el("p", state.autonomy ? "Routine stop-type calls are re-sent automatically, and you see each one below." : "Auto-resend is off. New proposals will wait for your decision."));
    $("inbox").replaceChildren(empty); return;
  }
  $("inbox").replaceChildren(...waiting.map((trace) => {
    const card = el("article", undefined, "decision");
    card.append(el("h3", names[trace.callsign] || trace.callsign), el("small", trace.callsign, "registration"), el("small", "MISSED · the tower’s words; highlighted words were talked over"), towerWords(trace));
    const why = el("p", undefined, "reason"); why.append(el("small", "Why you’re seeing this"), document.createTextNode(reason(trace))); card.append(why);
    // Elastic's Compliance agent cites the FAA rule; the hub keeps it only if that paragraph exists in unstep-faa.
    if (trace.proposal.rule_citation) {
      const rule = el("p", undefined, "citation"); rule.append(el("small", "The rule · cited by Elastic agents"), document.createTextNode(trace.proposal.rule_citation)); card.append(rule);
    }
    const failed = (trace.policy?.checks || []).filter((c) => !c.ok);
    if (failed.length > 1) {
      const more = el("details"); more.append(el("summary", `All ${failed.length} reasons`));
      failed.forEach((c) => more.append(el("p", state.reasons[c.name] || "An additional safety check failed.")));
      card.append(more);
    }
    const actions = el("div", undefined, "actions");
    for (const approve of [true, false]) {
      const button = el("button", approve ? "Approve and send" : "Reject", approve ? "approve" : "reject");
      button.dataset.event = trace.event_id;
      button.addEventListener("click", () => {
        if (now() >= trace.deadline_ms || state.pending.has(trace.event_id)) return;
        if (send({type:"decide",event_id:trace.event_id,approve})) { state.pending.add(trace.event_id); updateCountdowns(); }
      });
      actions.append(button);
    }
    const countdown = el("small", undefined, "countdown"); countdown.dataset.deadline = trace.deadline_ms || 0; countdown.dataset.event = trace.event_id;
    card.append(actions, countdown); return card;
  }));
  updateCountdowns();
}
function updateCountdowns() {
  document.querySelectorAll(".countdown").forEach((node) => {
    const seconds = Math.max(0, Math.ceil((Number(node.dataset.deadline) - now()) / 1000));
    const pending = state.pending.has(node.dataset.event);
    node.textContent = !seconds ? "Time expired · nothing will auto-send" : pending ? "Decision sent · waiting for confirmation" : `Auto-sends nothing · ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2,"0")} left`;
    node.parentElement.querySelectorAll("button").forEach((button) => { button.disabled = !state.ready || !seconds || pending; });
  });
}

// One lane per speaker. Heard lines are actual cockpit transcripts, never inferred.
function radioSentence(radio) {
  const overlapping = [...new Set((radio.overlaps || []).flatMap((o) => o.stations))];
  return overlapping.length ? `${overlapping.map(shortName).join(" and ")} talked at the same time; their radio calls were talked over.` : `${shortName(radio.transmissions.at(-1)?.station)} transmitted on the shared radio.`;
}
// Instructions move the planes, but only words a plane actually heard, or that Unstep delivered to it.
// A stepped-on call leaves the plane where it is; Unstep's private advisory then makes it obey.
// Every instruction a plane hears is then checked against its readback (instructions.js, tested).
let Words = null;
import("./instructions.js").then((m) => { Words = m; }).catch((error) => console.warn("Instruction parser", error));
const obeyed = new Set(), checked = new Set();
const awaitingReadback = new Map();  // station -> {instruction, text, at}
const READBACK_WINDOW_MS = 45000;
function obey(key, stationId, text) {
  if (!Words || obeyed.has(key) || !stationId) return;
  const instruction = Words.parseInstruction(text);
  if (!instruction.action) return;
  obeyed.add(key);
  // As on a real frequency (JO 7110.65 2-4-3, AIM 4-3): a stop acts at once; anything that moves the plane
  // waits for the pilot's readback, and only a correct one lets it go.
  if (instruction.action === "stop") { execute(stationId, instruction); return; }
  awaitingReadback.set(stationId, {instruction, text, at: now()});
  const id = `awaiting-${stationId}`;
  state.actions.set(id, {id, ts: now(), agent: "Readback check", kind: "rule", status: "needs_you", station: stationId,
    text: `${shortName(stationId)} was told “${text}”. Waiting for the readback before it moves.`});
  renderFeed();
}
const lastAction = new Map();  // station -> the last instruction it carried out
function execute(stationId, instruction) {
  lastAction.set(stationId, instruction.action);
  sceneCall("command", stationId, instruction.action, {via: instruction.via, runway: instruction.runway, dest: instruction.dest});
}
function readbackConfirmed(stationId) {
  // The cockpit's own readback check passed (an Unstep-delivered instruction): the plane may go.
  const pending = awaitingReadback.get(stationId);
  if (!pending) return;
  awaitingReadback.delete(stationId); state.actions.delete(`awaiting-${stationId}`);
  execute(stationId, pending.instruction);
  renderFeed();
}
function obeyIfHeard(tx) {
  // Give the cockpit a moment to report a blocked call; a plane that missed the words doesn't move.
  setTimeout(() => {
    if (!Words) return;
    const text = tx.text || state.lanes.get("atc")?.text || state.captions.get("atc")?.text;
    const target = Words.addressee(text, visibleAircraft());
    if (!target) return;
    const missed = [...state.traces.values()].some((tr) => tr.callsign === target.id && (tr.created_ms || 0) >= tx.start_ms - 1000);
    if (!missed) obey(`tx-${tx.start_ms}`, target.id, text);
  }, 1500);
}
// The Clearance agent: a pilot's request ("request taxi", "ready for departure") gets a proposed clearance built
// from its flight plan (Elastic), its last tower call (its Moss session) and where every plane is. Fixed rules
// in clearance.js decide; the controller sends it with one tap.
let Clearance = null;
import("./clearance.js").then((m) => { Clearance = m; }).catch((error) => console.warn("Clearance agent", error));
const requests = new Map();  // station -> {stationId, text, plan, last, proposal}
async function clearanceRequest(stationId, text) {
  const request = Clearance?.parseRequest(text);
  if (!request) return;
  let context = null;
  try { context = await (await fetch(`/live/clearance-context/${encodeURIComponent(stationId)}`)).json(); }
  catch (error) { console.warn("Clearance context", error); }
  const station = state.stations.get(stationId);
  const plan = context?.flight_plan?.runway ? context.flight_plan : {runway: "33", route: "Bravo", source: "console"};
  const planes = window.unstepAirport?.inspect?.() || [];
  const traffic = context?.runway_traffic;
  const proposal = Clearance.proposeClearance({callsign: station?.spoken || station?.callsign || stationId, request, plan,
    plane: planes.find((p) => p.id === stationId), others: planes.filter((p) => p.id !== stationId).map((p) => ({...p, name: shortName(p.id)})),
    runwayTraffic: Array.isArray(traffic?.planes) ? traffic.planes.map(shortName) : null});
  requests.set(stationId, {stationId, text, plan, last: context?.last_tower_call, traffic, proposal});
  const id = `clearance-${stationId}`;
  state.actions.set(id, {id, ts: now(), agent: "Clearance agent", kind: "rule", status: "needs_you", station: stationId,
    text: `${shortName(stationId)} asked “${text}”. Proposed: “${proposal.text}”`, sponsor: plan.source === "elastic" ? "Elastic" : null});
  renderRequests(); renderFeed();
}
// Geo: once a second the planes' positions go to the hub, which stores them in Elastic as geo points and asks
// which airport areas (Elastic geo shapes) each one is in. A change of area is posted to the feed; a plane that
// enters the runway without a line-up or take-off clearance is flagged as a runway incursion.
const geoAreas = new Map();
let geoBusy = false;
const ON_RUNWAY_OK = ["lined_up", "takeoff", "departed"];
async function trackGeo() {
  const planes = globalThis.window?.unstepAirport?.inspect?.() || [];
  if (geoBusy || !planes.length || globalThis.document?.hidden) return;
  geoBusy = true;
  try {
    const res = await (await fetch("/live/geo/positions", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({planes: planes.map(({id, x, z, alt, state: s}) => ({id, x, z, alt, state: s}))})})).json();
    const how = res.backend === "elastic" ? `Elastic geo_shape query, ${res.took_ms} ms` : "local copy of the areas";
    for (const [id, g] of Object.entries(res.planes || {})) {
      const areas = g.areas.join(", "), before = geoAreas.get(id);
      geoAreas.set(id, areas);
      if (before === areas) continue;  // first sighting or a new area: post it
      const where = areas || (g.alt_m > 20 ? "airborne" : "no marked area");
      state.actions.set(`geo-${id}`, {id: `geo-${id}`, ts: now(), agent: "Geo", kind: "agent", status: "done", station: id,
        text: `${shortName(id)} now in ${where} at ${g.lat.toFixed(5)}, ${g.lon.toFixed(5)} (${how})`, sponsor: res.backend === "elastic" ? "Elastic" : null});
      // on the runway is fine once lined up or rolling, or while taxiing there under a line-up or take-off clearance
      const cleared = ON_RUNWAY_OK.includes(g.state) || ["line_up", "takeoff"].includes(lastAction.get(id));
      if (areas.includes("Runway") && !(before || "").includes("Runway") && !cleared) {
        state.actions.set(`incursion-${id}`, {id: `incursion-${id}`, ts: now(), agent: "Geo", kind: "agent", status: "flag", station: id,
          text: `Runway incursion: ${shortName(id)} entered Runway 33/15 without a line-up or take-off clearance (${how})`, sponsor: "Elastic"});
        notice(`Runway incursion: ${shortName(id)} is on the runway without a clearance.`);
      }
      renderFeed();
    }
    proposeNextSteps(planes, res);
  } catch (error) { console.warn("Geo", error); }
  finally { geoBusy = false; }
}
if (globalThis.window) setInterval(trackGeo, 1000);

// The Clearance agent also works unasked, as a controller does: when a plane arrives somewhere (lined up, holding
// short, stopped at a taxiway point it was sent to) it proposes the next instruction. A plane waiting for traffic
// is checked again every second against Elastic's geo answer and gets its card the moment the runway is clear.
const stepDone = new Map();  // station -> the arrival it already has a proposal for
const plans = new Map();     // station -> flight plan, read once per flight
async function proposeNextSteps(planes, geo) {
  if (!Clearance?.nextStep) return;
  const onRunway = Object.entries(geo.planes || {}).filter(([, g]) => g.areas.some((a) => a.startsWith("Runway"))).map(([id]) => id);
  for (const plane of planes) {
    const id = plane.id, arrival = `${plane.state}:${plane.runway || ""}`;
    let card = requests.get(id);
    if (card?.auto && card.arrival !== arrival) { requests.delete(id); state.actions.delete(`clearance-${id}`); card = null; renderRequests(); renderFeed(); }
    if (!["lined_up", "holding", "stopped"].includes(plane.state)) { stepDone.delete(id); continue; }
    if (plane.state === "stopped" && lastAction.get(id) === "stop") continue;  // told to hold position: the controller decides when
    if (awaitingReadback.has(id) || (requests.has(id) && !card?.auto)) continue;
    if (stepDone.get(id) === arrival && !card) continue;  // proposed already and sent or dismissed
    if (!plans.has(id)) {
      try { const ctx = await (await fetch(`/live/clearance-context/${encodeURIComponent(id)}`)).json(); plans.set(id, ctx.flight_plan || null); }
      catch { plans.set(id, null); }
    }
    const plan = plans.get(id) || {runway: plane.runway || "33", route: "Bravo", source: "console"};
    const station = state.stations.get(id);
    const traffic = geo.backend === "elastic" ? onRunway.filter((o) => o !== id).map(shortName) : null;
    const step = Clearance.nextStep({callsign: station?.spoken || station?.callsign || id, plan, plane, runwayTraffic: traffic,
      others: planes.filter((o) => o.id !== id).map((o) => ({...o, name: shortName(o.id)}))});
    if (!step) {  // waiting for the runway: withdraw a card that is no longer safe, look again next second
      if (card?.auto) { requests.delete(id); state.actions.delete(`clearance-${id}`); stepDone.delete(id); renderRequests(); renderFeed(); }
      continue;
    }
    if (card?.auto) continue;  // still valid: keep the card on screen
    stepDone.set(id, arrival);
    requests.set(id, {stationId: id, auto: true, arrival, text: `${shortName(id)} ${step.situation}`, plan,
      traffic: traffic ? {planes: traffic, took_ms: geo.took_ms} : null, proposal: step});
    state.actions.set(`clearance-${id}`, {id: `clearance-${id}`, ts: now(), agent: "Clearance agent", kind: "rule", status: "needs_you", station: id,
      text: `${shortName(id)} ${step.situation}. Next: “${step.text}”`, sponsor: traffic ? "Elastic" : null});
    renderRequests(); renderFeed();
  }
}

function sendClearance(stationId) {
  const r = requests.get(stationId);
  if (!r || !send({type: "say", text: r.proposal.text})) return;
  requests.delete(stationId);
  const id = `clearance-${stationId}`;
  state.actions.set(id, {id, ts: now(), agent: "Clearance agent", kind: "rule", status: "done", station: stationId,
    text: `You sent “${r.proposal.text}” to ${shortName(stationId)}`, sponsor: r.plan.source === "elastic" ? "Elastic" : null});
  renderRequests(); renderFeed();
}
function renderRequests() {
  const box = $("requests");
  if (!box) return;
  box.replaceChildren(...[...requests.values()].map((r) => {
    const card = el("article", undefined, "decision clearance");
    card.append(el("h3", r.auto ? `Next for ${shortName(r.stationId)}` : `${shortName(r.stationId)} asks`), el("p", r.auto ? r.text : `“${r.text}”`, "words"));
    const facts = el("p", undefined, "reason");
    facts.append(el("small", "What the agent checked"));
    facts.append(el("span", `Flight plan: ${r.plan.summary || `runway ${r.plan.runway} via ${r.plan.route}`} (${r.plan.source === "elastic" ? `Elastic · ${r.plan.ms} ms` : "console default"})`));
    if (r.last?.text) facts.append(el("span", ` · Last tower call: “${r.last.text}” (${r.last.backend === "moss" ? "Moss" : "plane memory"} · ${r.last.ms} ms)`));
    if (Array.isArray(r.traffic?.planes)) facts.append(el("span", ` · Runway: ${r.traffic.planes.length ? r.traffic.planes.map(shortName).join(", ") + " on it" : "clear"} (Elastic geo · ${r.traffic.took_ms} ms)`));
    facts.append(el("span", ` · Why: ${r.proposal.reason}`));
    card.append(facts, el("p", `“${r.proposal.text}”`, "proposal"));
    const actions = el("div", undefined, "actions");
    const go = el("button", "Send clearance", "approve"); go.addEventListener("click", () => sendClearance(r.stationId));
    const no = el("button", "Dismiss", "reject"); no.addEventListener("click", () => { requests.delete(r.stationId); state.actions.delete(`clearance-${r.stationId}`); renderRequests(); renderFeed(); });
    actions.append(go, no); card.append(actions);
    return card;
  }));
}
function pilotSpoke(key, stationId, text) {
  // The plane's next call after an instruction is its readback: compare it with what the tower said.
  // A call that isn't a readback may be a request for the Clearance agent.
  if (!Words || !text || checked.has(key)) return;
  const pending = awaitingReadback.get(stationId);
  if (!pending || now() - pending.at > READBACK_WINDOW_MS) { checked.add(key); clearanceRequest(stationId, text); return; }
  checked.add(key);
  const who = shortName(stationId), result = Words.checkReadback(pending.instruction, text);
  const id = `readback-${key}`;
  state.actions.delete(`awaiting-${stationId}`);
  if (result.ok) {
    awaitingReadback.delete(stationId);
    sceneCall("readback", stationId, true);
    execute(stationId, pending.instruction);  // read back correctly: now the plane complies
    state.actions.set(id, {id, ts: now(), agent: "Readback check", kind: "rule", status: "done", station: stationId,
      text: `${who} read it back correctly and is moving.`, sponsor: "Cartesia"});
  } else {
    // Still waiting: a corrected readback inside the window lets the plane go.
    pending.at = now();
    const what = result.problems.map((x) => `said ${x.said}, the tower said ${x.expected}`).join("; ");
    sceneCall("readback", stationId, false);
    state.actions.set(id, {id, ts: now(), agent: "Readback check", kind: "rule", status: "flag", station: stationId,
      text: `Wrong readback from ${who}: ${what}. ${who} stays put until the readback is right.`, sponsor: "Cartesia"});
    $("happened").textContent = `${who} read back wrong: ${what}. ${who} isn't moving until the readback is right.`;
    notice(`Wrong readback from ${who}. Say the instruction again.`);
  }
  renderFeed();
}
function radioEvent(radio, announce = true) {
  radio.transmissions.forEach((tx) => {
    // An older cluster must not clear a newer live warning.
    if (state.liveOverlap.has(tx.station) && tx.end_ms >= state.liveOverlap.get(tx.station)) state.liveOverlap.delete(tx.station);
    const blocked = (radio.overlaps || []).some((o) => o.stations.includes(tx.station) && o.start_ms < tx.end_ms && o.end_ms > tx.start_ms);
    const prior = state.lanes.get(tx.station);
    if (!prior || tx.start_ms >= prior.start_ms) state.lanes.set(tx.station, {...tx, blocked});
    if (announce && tx.station === "atc" && !blocked && tx.end_ms) obeyIfHeard(tx);
    if (announce && tx.station !== "atc" && !blocked && tx.text) pilotSpoke(`tx-${tx.start_ms}`, tx.station, tx.text);
  });
  if (announce) { $("happened").textContent = radioSentence(radio); renderMap(); renderRadio(); }
}
function renderRadio() {
  const traces = tracesNewestFirst();
  // Every station keeps its lane; only the two most recently active are shown (the rest are "idle").
  const all = ["atc", ...visibleAircraft().map((s) => s.id)];
  const recent = new Set(all
    .filter((id) => state.lanes.has(id) || state.captions.has(id) || state.liveOverlap.has(id))
    // A lane being talked over right now always ranks first, even before its caption arrives.
    .sort((a, b) => Math.max(state.liveOverlap.has(b) ? Infinity : 0, state.lanes.get(b)?.start_ms || 0, state.captions.get(b)?.ts || 0) - Math.max(state.liveOverlap.has(a) ? Infinity : 0, state.lanes.get(a)?.start_ms || 0, state.captions.get(a)?.ts || 0))
    .slice(0, 2));
  $("radio").replaceChildren(...all.map((id) => {
    const tx = state.lanes.get(id);
    const row = el("div", undefined, recent.has(id) ? "lane" : "lane idle");
    row.dataset.station = id;
    const speaker = el("b", names[id] || shortName(id));
    if (id in state.keyed) speaker.append(el("small", "ON AIR", "on-air"));
    row.append(speaker);
    const caption = state.captions.get(id);
    const live = caption && (!tx?.start_ms || caption.ts >= tx.start_ms);
    const words = live ? captionLine(caption)
      : el("div", tx?.text || (tx ? "Voice transmission · transcript not available" : "No transmission yet"));
    const level = el("span", undefined, "level"); level.append(el("i"));
    words.append(level);
    if (id !== "atc") {
      const trace = traces.find((t) => t.callsign === id && t.event);
      words.append(el("span", trace ? `Heard at ${new Date(trace.created_ms).toLocaleTimeString()}: “${trace.event.heard_text || "[no words recovered]"}”` : "Heard: no cockpit transcript received yet", "heard"));
    }
    const recovery = state.recoveries.get(id);
    if (recovery) words.append(el("span", `Unstep told the tower: “${recovery.text.replace(/^Advisory\.\s*/, "")}”`, "heard recovery-line"));
    const report = state.reports.get(id);
    if (report) words.append(el("span", advisoryLine(report), `heard advisory-line${report.overlapped_ms > 0 ? " overlapped" : ""}`));
    row.append(words);
    if (tx?.blocked || state.liveOverlap.has(id)) row.append(el("span", "TALKED OVER", "talked-over"));
    return row;
  }));
}

// Captions: the words as Cartesia recognises them, with callsign, action and runway coloured.
function captionLine(c) {
  const line = el("div", undefined, `caption${c.final ? "" : " partial"}`);
  const words = el("span", undefined, "caption-words");
  for (const w of (c.words?.length ? c.words : c.text.split(" ").map((text) => ({text, kind: null})))) {
    if (typeof w !== "object") continue;
    words.append(el("span", w.text, w.kind ? `kw ${w.kind}` : undefined), " ");
  }
  line.append(words);
  const label = c.source === "tts" ? "Cartesia speech · TTS timing"
    : `Cartesia live caption${c.lag_ms != null ? ` · ${Math.round(c.lag_ms)} ms ${c.final ? "after release" : "behind speech"}` : ""}`;
  line.append(el("small", label, "caption-label"));
  return line;
}

// C5: proof that the private advisory spoke only in a gap.
function advisoryLine(r) {
  const s = (ms) => `${(ms / 1000).toFixed(1)} s`;
  const overlap = r.overlapped_ms > 0
    ? `overlapped ${r.overlapped_by.map(shortName).join(" and ")}: ${Math.round(r.overlapped_ms)} ms`
    : "overlapped nobody: 0 ms";
  return `Private advisory: waited ${s(r.waited_ms)} for a gap, spoke ${s(r.spoke_ms)}, ${overlap}${r.cancelled ? " · cut off by the pilot" : ""}`;
}

// Each step is a plain sentence, followed by honest attribution and measurements.
function steps(trace) {
  const list = el("ol");
  let readbackIndex = 0;
  for (const step of trace.steps || []) {
    const instruction = trace.proposal?.instruction_text || "the instruction";
    const hint = trace.event?.local_hint;
    const speech = state.live ? "Cartesia" : "Fake speech";
    let sentence = step.text, sponsor = "Unstep", agent = step.actor;
    switch (step.kind) {
      case "detected": sentence = `Heard a blocked radio call in ${shortName(trace.callsign)}’s cockpit.`; agent = "Cockpit agent"; break;
      case "hint": sentence = `The plane’s memory suggests “${hint?.text || "a stop instruction"}”; this is a hint, not permission.`; agent = "Cockpit agent"; sponsor = step.data?.backend === "moss" ? "Moss" : "Local memory"; break;
      case "moss_search": agent = "Cockpit agent"; sponsor = step.data?.backend === "moss" ? "Moss" : "Local memory"; break;
      case "proposed": {
        const cited = step.data?.citation;
        sentence = `Recovered “${instruction}”${trace.tower ? " from the tower’s own words" : " without a tower transcript"}.${cited ? ` Elastic’s Compliance agent cited ${cited}.` : ""}`;
        agent = "Ground agents"; sponsor = cited ? "Elastic agents" : "Local stand-in"; break;
      }
      case "agents_cited": sentence = `Elastic’s agents checked the fix and cited ${step.data?.citation || "the governing FAA rule"}${step.data?.workflow_ms ? ` (${(step.data.workflow_ms / 1000).toFixed(1)} s, after the card was shown)` : ""}.`; agent = "Ground agents"; sponsor = "Elastic agents"; break;
      case "auto_relay": sentence = "Every policy check passed, so the tower’s own stop/wait instruction can be re-sent."; agent = "Policy agent"; sponsor = "policy"; break;
      case "escalate": sentence = reason(trace); agent = "Policy agent"; sponsor = "policy"; break;
      case "approved": sentence = step.actor === "policy" ? "The policy approved a resend of the tower’s own instruction." : "The controller approved sending the recovered instruction."; agent = step.actor === "policy" ? "Policy agent" : "Controller"; sponsor = step.actor === "policy" ? "policy" : "Human"; break;
      case "delivered": sentence = `Spoke “${instruction}” privately into ${shortName(trace.callsign)}’s left ear.`; agent = "Cockpit agent"; sponsor = speech; break;
      case "readback": {
        const readback = trace.readbacks?.[readbackIndex++];
        sentence = readback ? `The pilot repeated “${readback.readback_text}”, which ${readback.match ? "matches" : "does not match"} the instruction.` : step.text;
        agent = "Readback agent"; sponsor = speech; break;
      }
      case "rejected": sentence = "The controller rejected the instruction, so the pilot must ask the tower to repeat it."; agent = "Controller"; sponsor = "Human"; break;
      case "expired": sentence = "No decision arrived in time, so nothing was sent."; agent = "Gateway"; break;
    }
    const metrics = Object.entries(step.data || {}).filter(([key,value]) => ["moss_ms","first_audio_ms","latency_ms","detection_ms"].includes(key) && typeof value === "number" && Number.isFinite(value));
    const time = metrics.length ? metrics.map(([key,value]) => `${value.toFixed(1)} ms${key === "first_audio_ms" ? " first audio" : ""}`).join(" · ") : "not measured";
    const item = el("li"); const meta = el("span", undefined, "step-meta");
    meta.append(document.createTextNode(agent || "Agent"), el("span", sponsor, "sponsor"), el("span", time, "timing"));
    item.append(el("span", sentence), meta); list.append(item);
  }
  return list;
}

// Timing waterfall for one event, from the hub's per-stage `timings` (all on the hub clock).
// Only real measurements are drawn; a stage the hub didn't report is simply absent.
const STAGES = {
  call_start: ["The call started", ""],
  keys_overlap: ["Two people pressed talk", ""],
  keys_detected: ["Unstep saw both keys down", ""],
  stepped_on: ["The calls overlapped", ""],
  call_end: ["The call ended", ""],
  cockpit_stt_final: ["Cartesia transcribed what the cockpit heard", "cartesia"],
  event_raised: ["The cockpit flagged a lost call", ""],
  moss_search: ["Moss searched the plane's memory", "moss"],
  hint: ["Moss found the likely instruction", "moss"],
  tower_stt_final: ["Cartesia finished the tower transcript", "cartesia"],
  tower_transcript: ["Cartesia transcribed the tower", "cartesia"],
  proposed: ["Ground agents proposed a resend", ""],
  agents_cited: ["Elastic agents cited the rule", "elastic"],
  policy: ["Policy agent checked it", ""],
  approved: ["Approved", "human"],
  rejected: ["Rejected", "human"],
  spoken: ["Cartesia spoke it to the pilot", "cartesia"],
  readback: ["The pilot read it back", "cartesia"],
  elastic_check: ["Elastic checked the readback", "elastic"],
};
function waterfall(trace) {
  const rows = (trace.timings || []).filter((t) => Number.isFinite(t.at_ms)).sort((a, b) => a.at_ms - b.at_ms);
  const box = el("div", undefined, "waterfall");
  if (rows.length < 2) return box;
  const start = rows[0].at_ms;
  // "stepped_on" carries the overlap length as a duration; everything else is a point in time.
  const end = Math.max(...rows.map((t) => t.at_ms + (t.stage === "stepped_on" && Number.isFinite(t.ms) ? t.ms : 0)));
  const span = Math.max(1, end - start);
  const callEnd = rows.find((t) => t.stage === "call_end");
  const spoken = rows.find((t) => t.stage === "spoken");
  const headline = callEnd && spoken && spoken.at_ms >= callEnd.at_ms
    ? `From the call ending to the pilot hearing the fix: ${((spoken.at_ms - callEnd.at_ms) / 1000).toFixed(1)} s`
    : "Timing of each step, measured on the hub";
  box.append(el("div", headline, "waterfall-title"));
  for (const t of rows) {
    const [label, sponsor] = STAGES[t.stage] || [t.stage.replaceAll("_", " "), ""];
    const row = el("div", undefined, "wf-row");
    const track = el("div", undefined, "wf-track");
    const bar = el("div", undefined, `wf-bar ${sponsor}`);
    bar.style.left = `${((t.at_ms - start) / span) * 100}%`;
    bar.style.width = `${Math.max(0.8, Number.isFinite(t.ms) && t.stage === "stepped_on" ? (t.ms / span) * 100 : 0.8)}%`;
    track.append(bar);
    const offset = `+${((t.at_ms - start) / 1000).toFixed(2)} s`;
    const took = Number.isFinite(t.ms) && t.stage !== "stepped_on" ? ` · ${t.ms.toFixed(t.ms < 10 ? 1 : 0)} ms` : "";
    row.append(el("span", label, "wf-label"), track, el("span", offset + took, "wf-time"));
    box.append(row);
  }
  return box;
}

// Audio is explicitly unlocked by a gesture. Simultaneous radio clips can overlap.
async function play(encoded) {
  if (!encoded || !state.audio || state.audio.state !== "running") return;
  try {
    const bytes = Uint8Array.from(atob(encoded), (c) => c.charCodeAt(0));
    const buffer = await state.audio.decodeAudioData(bytes.buffer);
    const source = state.audio.createBufferSource(); source.buffer = buffer;
    source.connect(state.audio.destination); source.start();
  } catch { notice("Audio could not play. The radio text is still available."); }
}
$("reset").addEventListener("click", () => {
  if (confirm("Reset the room? Every walk-up plane is disconnected and the board is cleared.")) send({type: "reset"});
});
$("sound").addEventListener("click", async () => {
  try {
    state.audio ||= new AudioContext(); await state.audio.resume();
    $("sound").textContent = "Sound on";
  } catch { notice("This browser could not enable audio."); }
});
$("autonomy").addEventListener("change", () => {
  const on = $("autonomy").checked;
  $("autonomy").checked = state.autonomy;
  send({type:"autonomy",on});
});
// Enter and the Transmit button share one path; requestSubmit() can be blocked by form state.
function transmitSay() {
  const text = $("say").value.trim();
  if (text && send({type:"say",text})) $("say").value = "";
}
$("say-form").addEventListener("submit", (event) => {
  event.preventDefault();
  transmitSay();
});
$("say").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.isComposing) {
    event.preventDefault();
    transmitSay();
  }
});
document.querySelectorAll("[data-say]").forEach((button) => button.addEventListener("click", () => send({type:"say",text:button.dataset.say})));
function showPilotLink(url) {
  $("join-url").textContent = url;
  $("join-url").href = url;
  $("join-qr").href = url;
  $("qr").src = `/live/qr.svg?u=${encodeURIComponent(url)}`;
  $("phone-hint").hidden = !["localhost", "127.0.0.1", "[::1]"].includes(new URL(url).hostname);
}
// Safety analytics from GET /live/stats (ES|QL on Elastic, or the hub's own counts when Elastic is off).
// Scoped to this console session so rehearsals never show up as this run's numbers.
const statsSince = Date.now();
async function loadStats() {
  try {
    const response = await fetch(`/live/stats?since_ms=${statsSince + (state.offset || 0)}`);
    if (!response.ok) throw new Error(String(response.status));
    const stats = await response.json();
    $("stat-blocked").textContent = stats.blocked_calls ?? 0;
    $("stat-readback").textContent = stats.readback_errors ?? 0;
    $("stat-auto").textContent = stats.auto_resends ?? 0;
    const elastic = stats.backend === "elastic";
    $("stats-source").textContent = elastic ? `Elastic ES|QL · ${Math.round(stats.took_ms ?? 0)} ms` : "Hub counts · Elastic not connected";
    $("stats-source").className = elastic ? "cyan" : "";
    // Simulated traffic is real processing of synthetic calls: always labelled, never shown as real usage.
    const simulated = stats.simulated_runs?.length || 0;
    $("stats-simulated").hidden = !simulated;
    $("stats-simulated").textContent = `Simulated traffic · ${simulated} run${simulated === 1 ? "" : "s"} included`;
    $("stat-esql").textContent = stats.esql || "No query: Elastic is not configured on this hub.";
  } catch {
    $("stats-source").textContent = "Analytics unavailable";
  }
}

async function loadPilotLink() {
  showPilotLink(`${location.origin}/pilot/${window.UNSTEP_TOKEN_QUERY || ""}`);
  try {
    const response = await fetch("/live/pilot-link");
    if (!response.ok) throw new Error("Pilot link unavailable");
    const {url} = await response.json();
    if (!["http:", "https:"].includes(new URL(url).protocol)) throw new Error("Invalid pilot link");
    showPilotLink(url);
  } catch { /* Keep the same-host seat picker available. */ }
}
loadPilotLink();
try { state.reasons = await (await fetch("/live/static/atc/reasons.json")).json(); }
catch { notice("Detailed policy wording unavailable; failed checks still require a human decision."); }
startAirport();
renderRadio(); controls(); connect();
setInterval(updateCountdowns, 250);
loadStats();
setInterval(loadStats, 5000);
