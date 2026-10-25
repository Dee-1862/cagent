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
// runwayTraffic: names of planes Elastic's geo query found on the runway, or null to judge from the planes' states.
export function proposeClearance({callsign, request, plan, plane, others = [], runwayTraffic = null}) {
  const rw = plan.runway, route = plan.route || "Bravo";
  const taxi = {text: `${callsign}, taxi to runway ${rw} via ${route}, hold short of runway ${rw}`,
    reason: `flight plan: departure runway ${rw} via ${route}`};
  if (request === "taxi" || !plane) return taxi;
  const atRunway = ["holding", "lined_up"].includes(plane.state);
  if (!atRunway) return {...taxi, reason: `${taxi.reason}; the plane isn't at the runway yet`};
  if (runwayTraffic) {
    if (runwayTraffic.length) return {text: `${callsign}, hold short of runway ${rw}, traffic on the runway`,
      reason: `Elastic geo: ${runwayTraffic.join(", ")} inside the runway area`};
    return {text: `${callsign}, runway ${rw}, cleared for takeoff`, reason: "Elastic geo: runway area clear, and the plane is at the runway"};
  }
  const busy = others.find((o) => ["lined_up", "takeoff"].includes(o.state));
  if (busy) return {text: `${callsign}, hold short of runway ${rw}, traffic on the runway`, reason: `runway occupied by ${busy.name || busy.id}`};
  return {text: `${callsign}, runway ${rw}, cleared for takeoff`, reason: "runway clear and the plane is at the runway"};
}

/**
 * What the tower says next when a plane reaches a point, without being asked; null while it should wait.
 * Lined up: cleared for takeoff once the runway ahead is clear. Holding short: cleared for takeoff once the
 * runway is clear (keeps holding while it isn't). Stopped on a taxiway: taxi on to its flight plan's runway.
 * `runwayTraffic` is who Elastic's geo query has on the runway (null: judge from the other planes' states).
 * Returns {text, situation, reason} or null.
 */
export function nextStep({callsign, plan, plane, others = [], runwayTraffic = null}) {
  if (!plane) return null;
  const rw = plane.runway || plan.runway, route = plan.route || "Bravo";
  const busy = runwayTraffic ?? others.filter((o) => ["lined_up", "takeoff"].includes(o.state)).map((o) => o.name || o.id);
  const how = runwayTraffic ? "Elastic geo" : "plane states";
  if (plane.state === "lined_up" || plane.state === "holding") {
    if (busy.length) return null;
    return {text: `${callsign}, runway ${rw}, cleared for takeoff`,
      situation: plane.state === "lined_up" ? `is lined up on runway ${rw}` : `is holding short of runway ${rw}`,
      reason: `${how}: runway ${rw} clear`};
  }
  if (plane.state === "stopped") {
    return {text: `${callsign}, taxi to runway ${rw} via ${route}, hold short of runway ${rw}`,
      situation: "has stopped on the taxiway", reason: `flight plan: departure runway ${rw} via ${route}`};
  }
  return null;
}
