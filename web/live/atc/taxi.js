// The airport's ground network: taxiways A and B, connectors A1-A4, and the two runway connectors
// (B1 at the runway 33 end, B2 at the runway 15 end). Pure geometry and routing, no three.js, so the
// scene draws from it and tests can drive it directly.

export const RWY_Z = 22, TWY_Z = 14, TWYA_Z = 4.5;
export const HOLD_Z = RWY_Z - 3.4;          // the painted hold-short line on a runway connector
export const HOLD_STOP_Z = HOLD_Z - 1.4;    // where a plane stops, nose behind the line
export const A_CONNECTORS = [["A1", -38], ["A2", -17], ["A3", 6], ["A4", 30]];
// name, x, runway it serves, take-off direction along x from that end
export const RUNWAY_CONNECTORS = [["B1", -33, "33", 1], ["B2", 33, "15", -1]];
export const RUNWAYS = Object.fromEntries(RUNWAY_CONNECTORS.map(([name, x, rwy, dir]) => [rwy, {connector: name, x, dir}]));
export const DEFAULT_RUNWAY = "33";
export const QUEUE_GAP = 6.5;
// Planes wait on taxiway B nose-west toward B1 (the runway 33 end); each new one joins behind.
export const queueSpot = (i) => ({x: -26 + i * QUEUE_GAP, z: TWY_Z});

const nodes = new Map(), edges = new Map();
function node(id, x, z) { nodes.set(id, {id, x, z}); edges.set(id, []); }
function link(a, b) {
  const p = nodes.get(a), q = nodes.get(b), d = Math.hypot(p.x - q.x, p.z - q.z);
  edges.get(a).push([b, d]); edges.get(b).push([a, d]);
}
const bxs = [...new Set([...A_CONNECTORS.map(([, x]) => x), ...RUNWAY_CONNECTORS.map(([, x]) => x)])].sort((a, b) => a - b);
bxs.forEach((x) => node(`B@${x}`, x, TWY_Z));
bxs.slice(1).forEach((x, i) => link(`B@${bxs[i]}`, `B@${x}`));
const axs = A_CONNECTORS.map(([, x]) => x).sort((a, b) => a - b);
axs.forEach((x) => node(`A@${x}`, x, TWYA_Z));
axs.slice(1).forEach((x, i) => link(`A@${axs[i]}`, `A@${x}`));
for (const [name, x] of A_CONNECTORS) { node(name, x, (TWY_Z + TWYA_Z) / 2); link(`B@${x}`, name); link(name, `A@${x}`); }
for (const [name, x, rwy] of RUNWAY_CONNECTORS) {
  node(`HOLD${rwy}`, x, HOLD_STOP_Z); node(`RWY${rwy}`, x, RWY_Z);
  link(`B@${x}`, `HOLD${rwy}`); link(`HOLD${rwy}`, `RWY${rwy}`);
}
link("RWY33", "RWY15");  // the runway itself, for backtracking and runway exits

// Named places a controller can send a plane to.
export function placeNode(place) {
  if (!place) return null;
  if (/^A[1-4]$/.test(place)) return place;
  const conn = RUNWAY_CONNECTORS.find(([name]) => name === place);
  return conn ? `HOLD${conn[2]}` : null;
}

function nearestNode(p, filter = () => true) {
  let best = null, bd = Infinity;
  for (const n of nodes.values()) {
    if (!filter(n)) continue;
    const d = Math.hypot(n.x - p.x, n.z - p.z);
    if (d < bd) { bd = d; best = n.id; }
  }
  return best;
}

function shortest(from, to, allowed = () => true) {
  const dist = new Map([[from, 0]]), prev = new Map(), todo = new Set([from]);
  while (todo.size) {
    let u = null;
    for (const n of todo) if (u === null || dist.get(n) < dist.get(u)) u = n;
    todo.delete(u);
    if (u === to) break;
    for (const [v, w] of edges.get(u)) {
      if (!allowed(v) && v !== to) continue;
      const d = dist.get(u) + w;
      if (d < (dist.get(v) ?? Infinity)) { dist.set(v, d); prev.set(v, u); todo.add(v); }
    }
  }
  if (!dist.has(to)) return null;
  const out = [to];
  while (out[0] !== from) out.unshift(prev.get(out[0]));
  return out;
}

/** Points ({x, z}) from position `from` to graph node `to`; `via: ["A"]` forces a run along taxiway A. */
export function route(from, to, {via = []} = {}) {
  const start = nearestNode(from);
  let ids;
  if (via.includes("A")) {
    const entry = nearestNode(from, (n) => n.id.startsWith("A@"));
    const goal = nodes.get(to);
    const exit = nearestNode(goal, (n) => n.id.startsWith("A@") && n.id !== entry) ?? entry;
    const a = shortest(start, entry), b = shortest(entry, exit, (id) => id.startsWith("A@")), c = shortest(exit, to);
    ids = a && b && c ? [...a, ...b.slice(1), ...c.slice(1)] : shortest(start, to);
  } else {
    // Without "via Alpha" stay off taxiway A unless the destination is up there.
    ids = shortest(start, to, (id) => !id.startsWith("A@")) ?? shortest(start, to);
  }
  if (!ids) return [];
  const pts = ids.map((id) => ({x: nodes.get(id).x, z: nodes.get(id).z}));
  if (Math.hypot(pts[0].x - from.x, pts[0].z - from.z) < .05) pts.shift();
  return pts;
}

export const holdNode = (rwy) => `HOLD${RUNWAYS[rwy] ? rwy : DEFAULT_RUNWAY}`;
export const runwayNode = (rwy) => `RWY${RUNWAYS[rwy] ? rwy : DEFAULT_RUNWAY}`;
/** Route to the runway end and a short step along it, so the plane faces the take-off direction. */
export function lineUpRoute(from, rwy, opts) {
  const r = RUNWAYS[rwy] ?? RUNWAYS[DEFAULT_RUNWAY];
  return [...route(from, runwayNode(rwy), opts), {x: r.x + r.dir * 2, z: RWY_Z}];
}
