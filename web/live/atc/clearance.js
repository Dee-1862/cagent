// The Clearance agent's decision: a pilot asks ("request taxi", "ready for departure"); with the plane's flight
// plan (from Elastic), where the plane is and whether the runway is free, fixed rules pick the clearance and
// say why. No model decides a clearance; the controller sends it or not. Pure, tested.
import {normalizeCall} from "./instructions.js";

/** "departure" (ready / request take-off), "taxi" (request taxi), or null when the call isn't a request. */
export function parseRequest(text) {
  const t = normalizeCall(text);
  if (/\b(ready|request(ing)?)\b.{0,16}\b(departure|take ?off)\b/.test(t)) return "departure";
  if (/\brequest(ing)?\b.{0,10}\btaxi\b|\bready to taxi\b/.test(t)) return "taxi";
  return null;
}

/**
 * `plan` {runway, route}; `plane` the asking plane's scene state; `others` the other planes' states.
 * Returns {text, reason}. The runway counts as busy while another plane is lined up or taking off.
 */
export function proposeClearance({callsign, request, plan, plane, others = []}) {
  const rw = plan.runway, route = plan.route || "Bravo";
  const taxi = {text: `${callsign}, taxi to runway ${rw} via ${route}, hold short of runway ${rw}`,
    reason: `flight plan: departure runway ${rw} via ${route}`};
  if (request === "taxi" || !plane) return taxi;
  const atRunway = ["holding", "lined_up"].includes(plane.state);
  if (!atRunway) return {...taxi, reason: `${taxi.reason}; the plane isn't at the runway yet`};
  const busy = others.find((o) => ["lined_up", "takeoff"].includes(o.state));
  if (busy) return {text: `${callsign}, hold short of runway ${rw}, traffic on the runway`, reason: `runway occupied by ${busy.name || busy.id}`};
  return {text: `${callsign}, runway ${rw}, cleared for takeoff`, reason: "runway clear and the plane is at the runway"};
}
