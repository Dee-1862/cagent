// The team strip: who is on the team and who decides. Compact and collapsed by default (the Agents panel is 360 px
// wide and the decision cards must stay in view). It is mostly structure; the dots and counts are only what this
// page has actually seen, through its own read-only observer socket. Nothing here changes a route or a decision.

const root = document.getElementById("team-strip");

// Each node: what it is, what it may do, and which step on a trace proves it ran (null = not visible from here).
const TEAM = [
  { id: "controller", level: 0, name: "Controller", role: "A person. Decides every proposal that moves a plane." },
  { id: "orchestrator", level: 1, name: "Orchestrator", role: "Elastic Workflow, fixed steps. Not an AI agent.", saw: "agents_cited" },
  { id: "intercept", level: 2, name: "Intercept agent", role: "What was lost on the radio?", saw: "agents_cited" },
  { id: "compliance", level: 2, name: "Compliance agent", role: "Which FAA paragraph governs it?", saw: "agents_cited" },
  { id: "auditor", level: 2, name: "Readback auditor", role: "Why did a readback not match?", saw: "percolate" },
  { id: "audit", level: 2, name: "Audit agent", role: "Answers from the audit trail when asked.", saw: null },
  { id: "coach", level: 2, name: "Coach agent", role: "How controllers decided over 30 days. No trend without enough data.", saw: null },
];
const BESIDE = [
  { id: "policy", name: "Policy agent", role: "Resends the tower's own stop calls after 7 checks.", saw: ["auto_relay", "escalate"] },
  { id: "cockpit", name: "Cockpit agents", role: "One per plane: Cartesia hears and speaks, Moss remembers.", saw: ["proposed"] },
];

const seen = new Map();  // node id -> {count, at}
const counted = new Set();
let open = false;
try { open = localStorage.getItem("unstep.team") === "open"; } catch { /* private mode */ }

const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

function note(trace) {
  for (const step of trace.steps || []) {
    const key = `${trace.event_id}:${step.kind}:${step.ts}`;
    if (counted.has(key)) continue;
    counted.add(key);
    for (const node of [...TEAM, ...BESIDE]) {
      const kinds = [].concat(node.saw || []);
      if (kinds.includes(step.kind)) {
        const s = seen.get(node.id) || { count: 0, at: 0 };
        seen.set(node.id, { count: s.count + 1, at: Date.now() });
      }
    }
  }
}

function waitingForYou() {
  return Number(document.getElementById("decision-count")?.textContent || 0);
}

function dotState(node) {
  if (node.id === "controller") return waitingForYou() > 0 ? "needs" : "idle";
  const s = seen.get(node.id);
  return s && Date.now() - s.at < 6000 ? "active" : s ? "seen" : "idle";
}

function line(node, level) {
  const row = el("div", `team-row level-${level}`);
  const state = dotState(node);
  const dot = el("i", `team-dot ${state}`);
  dot.title = { idle: "Nothing seen yet", seen: "Has run in this session", active: "Ran just now", needs: "Waiting for you" }[state];
  const text = el("div", "team-text");
  text.append(el("b", null, node.name), el("small", null, node.role));
  row.append(dot, text);
  const s = seen.get(node.id);
  if (node.id === "controller") row.append(el("span", "team-count", waitingForYou() ? `${waitingForYou()} waiting` : ""));
  else if (s) row.append(el("span", "team-count", `${s.count} seen`));
  return row;
}

let lastDrawn = "";
function render() {
  if (!root) return;
  // Redraw only when something changed, so a click is never lost to a redraw in the middle of it.
  const signature = JSON.stringify([open, waitingForYou(), [...TEAM, ...BESIDE].map((n) => [n.id, seen.get(n.id)?.count ?? 0, dotState(n)])]);
  if (signature === lastDrawn) return;
  lastDrawn = signature;
  root.replaceChildren();
  const head = el("button", "team-head");
  head.type = "button";
  head.setAttribute("aria-expanded", String(open));
  head.append(el("span", "team-title", "The team"),
    el("small", null, "1 person · 1 workflow · 5 agents"), el("span", "team-caret", open ? "⌃" : "⌄"));
  head.addEventListener("click", () => {
    open = !open;
    try { localStorage.setItem("unstep.team", open ? "open" : "closed"); } catch { /* ignore */ }
    render();
  });
  root.append(head);
  if (!open) return;
  const body = el("div", "team-body");
  TEAM.forEach((node) => body.append(line(node, node.level)));
  body.append(el("div", "team-sep", "Beside them"));
  BESIDE.forEach((node) => body.append(line(node, 0)));
  body.append(el("p", "team-foot",
    "A fixed workflow runs the agents and a person decides. Eight agents are configured: three are fast variants of Intercept and Compliance. "
    + "Counts are what this page has seen since it opened; without UNSTEP_ELASTIC_AGENTS the agents run as local stand-ins."));
  root.append(body);
}

function listen() {
  const hubHost = location.hostname.endsWith(".vercel.app") && window.UNSTEP_HUB_HOST && !window.UNSTEP_HUB_HOST.startsWith("__")
    ? window.UNSTEP_HUB_HOST : location.host;
  let ws;
  const connect = () => {
    ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${hubHost}/live/ws/observer${window.UNSTEP_TOKEN_QUERY || ""}`);
    ws.onmessage = (event) => {
      let m;
      try { m = JSON.parse(event.data); } catch { return; }
      if (m.type === "hello") (m.traces || []).forEach(note);
      else if (m.type === "trace" && m.trace) note(m.trace);
      else return;
      render();
    };
    ws.onclose = () => setTimeout(connect, 5000);
    ws.onerror = () => ws.close();
  };
  connect();
}

if (root) {
  render();
  listen();
  setInterval(render, 2000);  // dots fade and the "waiting for you" count follows the decision list
}
