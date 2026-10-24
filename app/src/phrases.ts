// What a pilot can say with one tap, written the way it is spoken on frequency.

const DIGITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "niner"];

/** "Piper 7-8-9" -> "Piper seven eight niner" (ATC says niner). */
export function sayable(spoken: string): string {
  return spoken.replace(/\d(-\d)*/g, (m) => m.split("-").map((d) => DIGITS[Number(d)]).join(" "));
}

export function sayLines(spoken: string, isHelicopter: boolean): { label: string; text: string; note?: string }[] {
  const me = sayable(spoken);
  const lines = [
    { label: "Read back: hold short 33", text: `Hold short runway three three, ${me}.` },
    { label: "Read back wrong: 23", text: `Hold short runway two three, ${me}.`, note: "wrong on purpose" },
    { label: "Ready for departure", text: `Tower, ${me}, ready for departure runway three three.` },
  ];
  if (isHelicopter) {
    lines.push({ label: "Request transition", text: `Tower, ${me}, request transition over the field, northbound.` });
  } else {
    lines.push({ label: "Request taxi", text: `Ground, ${me}, at the ramp, request taxi to runway three three.` });
  }
  return lines;
}

export const ASK_LINES = [
  "Unstep, what was my last clearance?",
  "Unstep, which runway was I told to stop at?",
  "Unstep, say again.",
  "Unstep, what did the tower tell me in the last minute?",
];
