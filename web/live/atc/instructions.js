// What a radio call says, in plain data: who it is for, what to do, which runway, where, via what.
// Also checks a pilot's readback against the instruction. Pure functions, tested in tests/test_atc_taxi.py.

const NUMBER_WORDS = {zero: "0", one: "1", two: "2", three: "3", tree: "3", four: "4", fower: "4", five: "5",
  fife: "5", six: "6", seven: "7", eight: "8", nine: "9", niner: "9"};

/** Lower case, number words to digits, spaced digits joined: "Cessna one, two, three" -> "cessna 123". */
export function normalizeCall(text) {
  return String(text || "").toLowerCase().replace(/[-,.!?;:]/g, " ").split(/\s+/).filter(Boolean)
    .map((w) => NUMBER_WORDS[w] ?? w).join(" ").replace(/(\d)\s+(?=\d)/g, "$1");
}

/** The station a call is addressed to, by its spoken callsign ("Cessna 1-2-3") or its name ("Plane A"). */
export function addressee(text, stations) {
  const t = normalizeCall(text);
  return stations.find((s) => {
    const spoken = normalizeCall(s.spoken || s.callsign || ""), type = spoken.split(" ")[0], digits = spoken.replace(/\D/g, "");
    const name = String(s.name || "").toLowerCase();
    return (digits && t.includes(digits) && (!type || /\d/.test(type) || t.includes(type))) || (name && t.includes(name));
  }) ?? null;
}

const PLACE = /\b(alpha|bravo|a|b)\s?([1-4])\b/;
const letter = (w) => w[0].toUpperCase();

export function parseInstruction(text) {
  const t = normalizeCall(text);
  const rw = t.match(/\brunway\s+(\d{1,2})\b/);
  const runway = rw ? rw[1].padStart(2, "0") : null;
  let action = null;
  if (/\bclear(ed)?\b.{0,16}\btake ?off\b|\btake ?off\b.{0,16}\bclear(ed)?\b/.test(t)) action = "takeoff";
  else if (/\bline ?up\b/.test(t)) action = "line_up";
  else if (/\bhold short\b/.test(t)) action = "hold_short";
  else if (/\bhold position\b|\bstop\b/.test(t)) action = "stop";
  else if (/\btaxi\b/.test(t)) action = "taxi";
  const after = t.match(/\b(to|at|of)\s+(.*)/);
  const placeMatch = after ? after[2].match(PLACE) : null;
  const dest = placeMatch ? `${letter(placeMatch[1])}${placeMatch[2]}` : null;
  const via = (() => {
    const m = t.match(/\bvia\b(.*)/);
    return m ? [...m[1].matchAll(/\b(alpha|bravo|a|b)\b(?!\s?[1-4])/g)].map((x) => letter(x[1])) : [];
  })();
  return {action, runway, dest, via};
}

const ACTION_WORDS = {takeoff: "cleared for takeoff", line_up: "line up and wait", hold_short: "hold short", stop: "hold position", taxi: "taxi"};

/**
 * Compare a readback with the instruction it answers. Returns {ok, problems}; each problem names the
 * field, what the pilot said and what the tower said. A missing runway or a missing "hold short" counts:
 * those are the parts a pilot must read back.
 */
export function checkReadback(instruction, readbackText) {
  const said = parseInstruction(readbackText), problems = [];
  if (instruction.runway && said.runway !== instruction.runway)
    problems.push({field: "runway", said: said.runway ? `runway ${said.runway}` : "no runway", expected: `runway ${instruction.runway}`});
  const mustSay = ["takeoff", "line_up", "hold_short"].includes(instruction.action);
  if (instruction.action && said.action !== instruction.action && (mustSay || said.action))
    problems.push({field: "instruction", said: said.action ? ACTION_WORDS[said.action] : "not read back", expected: ACTION_WORDS[instruction.action]});
  if (instruction.dest && said.dest !== instruction.dest)
    problems.push({field: "taxiway", said: said.dest ?? "no taxiway", expected: instruction.dest});
  return {ok: problems.length === 0, problems, said};
}
