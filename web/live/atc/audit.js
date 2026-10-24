// "Ask the audit trail": a controller's question about the last hour, answered by an Elastic agent over ES|QL.
// Self-contained: it adds its own panel only when the hub says Elastic is connected, and never touches the
// radio. The answer shows the ES|QL that produced it. Not part of the live safety path.
const token = window.UNSTEP_TOKEN_QUERY || "";
const withToken = (path) => `${path}${token}`;

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
  form.append(input, ask);
  const out = el("div", undefined, "audit-out"); out.setAttribute("aria-live", "polite");
  panel.append(title, form, out);
  (document.querySelector("section.analytics") || document.querySelector("main") || document.body).after(panel);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = input.value.trim();
    if (!question) return;
    ask.disabled = true; out.replaceChildren(el("p", "Asking Elastic...", "muted"));
    try {
      const body = await (await fetch(withToken("/live/ask-audit"), {
        method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify({question})})).json();
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
start();
