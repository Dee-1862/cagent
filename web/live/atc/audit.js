// "Ask the audit trail": a controller's question about the last hour, answered by an Elastic agent over ES|QL.
// A switch addresses the coach instead (how controllers decided over 30 days). Below it, the newest shift
// briefing and nightly review saved by the Elastic workflows, each with "Run now".
// Self-contained: it adds its own panel only when the hub says Elastic is connected, and never touches the
// radio. The answer shows the ES|QL that produced it. Not part of the live safety path.
const token = window.UNSTEP_TOKEN_QUERY || "";
const withToken = (path) => `${path}${path.includes("?") ? token.replace(/^\?/, "&") : token}`;

const el = (tag, text, cls) => { const n = document.createElement(tag); if (text) n.textContent = text; if (cls) n.className = cls; return n; };

async function start() {
  let available = false;
  try { available = (await (await fetch(withToken("/live/ask-audit"))).json()).available; } catch { /* hub older than this panel */ }
  if (!available) return;
  const panel = el("section", undefined, "panel audit");
  const title = el("div", undefined, "section-title");
  title.append(el("h2", "Ask the audit trail"), el("small", "Elastic agent over ES|QL, last hour, read only"));
  const form = el("form"); form.setAttribute("aria-label", "Ask the audit trail");
  const input = el("input"); input.type = "text"; input.maxLength = 300; input.placeholder = "Which plane was blocked most in the last hour?";
  input.setAttribute("aria-label", "Question about the last hour");
  const ask = el("button", "Ask"); ask.type = "submit";
  const who = el("select"); who.setAttribute("aria-label", "Which Elastic agent");
  for (const [value, label] of [["audit", "Audit trail · last hour"], ["coach", "Coach · 30-day trends"]]) {
    const o = el("option", label); o.value = value; who.append(o);
  }
  who.addEventListener("change", () => {
    input.placeholder = who.value === "coach" ? "Are controllers rejecting more proposals lately?" : "Which plane was blocked most in the last hour?";
  });
  form.append(who, input, ask);
  const out = el("div", undefined, "audit-out"); out.setAttribute("aria-live", "polite");
  panel.append(title, form, out, reportsBlock());
  (document.querySelector("section.analytics") || document.querySelector("main") || document.body).after(panel);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = input.value.trim();
    if (!question) return;
    ask.disabled = true; out.replaceChildren(el("p", "Asking Elastic...", "muted"));
    try {
      const body = await (await fetch(withToken("/live/ask-audit"), {
        method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify({question, agent: who.value})})).json();
      const parts = [];
      if (body.ok) {
        parts.push(el("p", body.answer));
        if (body.esql?.length) { const d = el("details"); d.append(el("summary", "The ES|QL that answered this"), el("pre", body.esql.join("\n\n"))); parts.push(d); }
        parts.push(el("small", `Elastic agent ${body.agent || ""} · ${body.took_ms} ms${body.tools?.length ? " · " + body.tools.join(", ") : ""}`));
      } else {
        parts.push(el("p", body.error || "No answer.", "muted"));
      }
      out.replaceChildren(...parts);
    } catch {
      out.replaceChildren(el("p", "The hub didn't answer.", "muted"));
    } finally { ask.disabled = false; }
  });
}
// The newest briefing and review (Elastic workflows: briefing every 8 h, review daily), read from their indexes.
function reportsBlock() {
  const box = el("div", undefined, "reports");
  box.append(el("h3", "Reports from Elastic workflows"));
  const row = el("div", undefined, "report-buttons");
  const view = el("div", undefined, "report-view"); view.setAttribute("aria-live", "polite");
  const kinds = [["briefing", "Shift briefing", "every 8 hours"], ["review", "Nightly review", "daily"]];
  let showing = null;
  const show = async (which) => {
    showing = which;
    view.replaceChildren(el("p", "Reading from Elastic...", "muted"));
    let body = null;
    try { body = await (await fetch(withToken("/live/reports"))).json(); } catch { /* shown below */ }
    if (showing !== which) return;
    const [, label, every] = kinds.find(([k]) => k === which);
    if (!body?.available) { view.replaceChildren(el("p", "Elastic isn't connected here.", "muted")); return; }
    const report = body[which];
    const head = el("div", undefined, "report-head");
    head.append(el("b", label), el("small", report?.at ? `saved ${new Date(report.at).toLocaleString()} · runs ${every}` : `none saved yet · runs ${every}`));
    const run = el("button", "Run now"); run.type = "button";
    run.addEventListener("click", async () => {
      run.disabled = true; run.textContent = "Running...";
      try {
        const r = await (await fetch(withToken(`/live/reports/run?which=${which}`), {method: "POST"})).json();
        run.textContent = r.ok ? "Started" : "Not started";
        view.append(el("small", r.ok ? (r.note || "Started; it saves in about a minute. Open it again then.") : (r.error || "Could not start it."), "muted"));
      } catch { run.textContent = "Not started"; }
    });
    head.append(run);
    view.replaceChildren(head, el("p", report?.text || "Nothing saved yet. Run it now to make the first one.", report?.text ? "report-text" : "muted"));
  };
  for (const [which, label] of kinds) {
    const b = el("button", label); b.type = "button";
    b.addEventListener("click", () => show(which));
    row.append(b);
  }
  box.append(row, view);
  return box;
}
start();
