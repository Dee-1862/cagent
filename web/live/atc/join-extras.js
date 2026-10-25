// Two small buttons under the console's QR: "Change link" (swap localhost for an address people can open) and
// "Raspberry Pi" (how to add a Pi as one more plane). They only call the hub's /live/addresses, /live/pilot-link
// and /live/pi-join; the QR itself is still drawn by the console.

const box = document.querySelector(".pilot-join");
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const isLocal = (url) => ["localhost", "127.0.0.1", "[::1]"].includes(new URL(url).hostname);

let pop = null;
function closePop() { pop?.remove(); pop = null; clearInterval(closePop.timer); }
function openPop(title) {
  closePop();
  pop = el("div", "join-pop");
  pop.setAttribute("role", "dialog");
  const head = el("div", "join-pop-head");
  const close = el("button", "join-pop-close", "×");
  close.type = "button";
  close.setAttribute("aria-label", "Close");
  close.addEventListener("click", closePop);
  head.append(el("b", null, title), close);
  pop.append(head);
  document.body.append(pop);
  const rect = box.getBoundingClientRect();
  pop.style.left = `${Math.max(12, rect.left)}px`;
  pop.style.bottom = `${window.innerHeight - rect.top + 8}px`;
  return pop;
}
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePop(); });
document.addEventListener("click", (e) => { if (pop && !pop.contains(e.target) && !box.contains(e.target)) closePop(); });

function showLink(url) {  // the same four things the console does when it learns the pilot link
  $("join-url").textContent = url;
  $("join-url").href = url;
  $("join-qr").href = url;
  $("qr").src = `/live/qr.svg?u=${encodeURIComponent(url)}`;
  const hint = $("phone-hint");
  if (hint) hint.hidden = !isLocal(url);
}

async function changeLink() {
  const p = openPop("Open this on phones");
  const list = el("div", "join-list");
  p.append(list);
  let data;
  try {
    const response = await fetch("/live/addresses");
    if (!response.ok) throw new Error(String(response.status));
    data = await response.json();
  } catch { list.append(el("p", "join-note join-warn", "This hub does not list addresses yet. Restart it (it was started before this update).")); return; }
  const current = $("join-url").textContent;
  for (const option of data.options) {
    const row = el("button", "join-opt");
    row.type = "button";
    const dot = el("i", `team-dot ${option.shareable ? "seen" : "needs"}`);
    dot.title = option.shareable ? "Phones can open this" : "Only this computer can open this";
    const text = el("div", "team-text");
    text.append(el("b", null, option.label), el("small", null, option.url));
    if (option.note) text.append(el("small", "join-warn", option.note));
    row.append(dot, text);
    if (current.startsWith(option.url)) row.append(el("span", "team-count", "in use"));
    row.addEventListener("click", async () => {
      try {
        const response = await fetch(`/live/pilot-link?base=${encodeURIComponent(option.url)}`);
        if (!response.ok) throw new Error(String(response.status));
        showLink((await response.json()).url);
        closePop();
      } catch { row.append(el("span", "team-count", "refused")); }
    });
    list.append(row);
  }
  if (!data.has_public) {
    const cmd = "python scripts/demo_public.py";
    const row = el("div", "join-copy");
    row.append(el("code", "join-code", cmd));
    const copy = el("button", "pill", "Copy");
    copy.type = "button";
    copy.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(cmd); copy.textContent = "Copied"; } catch { copy.textContent = "Select and copy"; }
    });
    row.append(copy);
    p.append(el("p", "join-note", "Most reliable: a public https link that works on any network, even phone data. Stop this hub and start it with:"));
    p.append(row);
    p.append(el("p", "join-note", "Anyone with that link can open the tower console, so set UNSTEP_ATC_PASSWORD in .env first."));
  } else {
    p.append(el("p", "join-note", "The public link works on any network. Anyone who has it can reach the tower console, so keep UNSTEP_ATC_PASSWORD set."));
  }
}

async function addPi() {
  const p = openPop("Add a Raspberry Pi");
  const body = el("div", "join-list");
  p.append(body);
  let info;
  try {
    const response = await fetch("/live/pi-join");
    if (!response.ok) throw new Error(String(response.status));
    info = await response.json();
  } catch { body.append(el("p", "join-note join-warn", "This hub cannot give the Pi command yet. Restart it (it was started before this update).")); return; }
  body.append(el("p", "join-note", "The Pi joins as one more plane and talks with its own microphone."));
  const code = el("code", "join-code", info.command);
  const copy = el("button", "pill", "Copy");
  copy.type = "button";
  copy.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(info.command); copy.textContent = "Copied"; }
    catch { copy.textContent = "Select and copy"; }
  });
  const row = el("div", "join-copy");
  row.append(code, copy);
  body.append(row);
  if (info.needs_token) body.append(el("p", "join-note", "Replace <room code> with this room's code."));
  if (!info.shareable) body.append(el("p", "join-note join-warn", "This address only works on this computer. Start the hub with --host 0.0.0.0 so the Pi can reach it."));
  body.append(el("p", "join-note",
    "On the Pi: sudo apt install python3-websockets alsa-utils, copy scripts/pi_plane.py, then run the command. "
    + "Add --mic plughw:3,0 (see arecord -l) to choose the microphone; press Enter to talk and again to stop."));
  const status = el("p", "join-status");
  const dot = el("i", "team-dot idle");
  const label = el("span", null, "Waiting for the Pi to join");
  status.append(dot, label);
  body.append(status);
  const count = (d) => Object.values(d.connected || {}).reduce((a, b) => a + b, 0);
  let base;
  closePop.timer = setInterval(async () => {
    try {
      const d = await (await fetch("/live/stations")).json();
      if (base === undefined) base = count(d);
      if (count(d) > base) { dot.className = "team-dot seen"; label.textContent = "A plane joined. Check it is the Pi on the radio lane."; }
    } catch { /* keep waiting */ }
  }, 2000);
}

if (box) {
  const actions = el("div", "join-actions");
  const change = el("button", "pill", "Change link");
  const pi = el("button", "pill", "Raspberry Pi");
  for (const b of [change, pi]) b.type = "button";
  change.addEventListener("click", () => (pop ? closePop() : changeLink()));
  pi.addEventListener("click", () => (pop ? closePop() : addPi()));
  actions.append(change, pi);
  box.append(actions);
}
