// Recording-session page: start/stop, live counters, and the tower's next line.
const $ = (id) => document.getElementById(id);
let ws = null, on = false;

function connect() {
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/live/ws/atc${window.UNSTEP_TOKEN_QUERY || ""}`);
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.type === "auth_required") {
      const password = prompt("ATC password");
      ws.send(JSON.stringify({ type: "auth", password: password || "" }));
    } else if (m.type === "hello") {
      $("state").textContent = "connected";
      $("toggle").disabled = false;
      show(m.recording);
    } else if (m.type === "recording") {
      show(m);
    } else if (m.type === "prompt" && m.station === "atc") {
      $("line").textContent = m.line;
      $("to").textContent = m.plane ? `to ${m.plane}` : "";
    } else if (m.type === "prompt" && m.cue === "talk_now") {
      $("to").textContent = `${$("to").textContent}  ·  cued: ${m.station} talks over you now`;
    } else if (m.type === "status") {
      $("state").textContent = m.text;
    }
  };
  ws.onclose = () => { $("state").textContent = "reconnecting..."; $("toggle").disabled = true; setTimeout(connect, 1500); };
}

function show(r) {
  on = Boolean(r && r.on);
  $("toggle").textContent = on ? "Stop recording" : "Start recording";
  $("toggle").className = on ? "stop" : "";
  $("state").innerHTML = on ? `<span class="rec">● REC</span> ${r.session}` : "not recording";
  for (const k of ["clips", "overlaps", "mixes", "flagged", "dropped"]) $(k).textContent = r && r[k] != null ? r[k] : $(k).textContent;
  if (r && r.by_speaker) $("speakers").textContent = Object.entries(r.by_speaker).map(([n, c]) => `${n}: ${c}`).join(" · ");
}

$("toggle").addEventListener("click", () => {
  if (!on && !$("consent").checked) { $("state").textContent = "Tick the consent box first."; return; }
  ws.send(JSON.stringify({ type: "recording", on: !on, session: $("session").value.trim(), name: $("name").value.trim() || "Tower", consent: $("consent").checked }));
});
connect();
