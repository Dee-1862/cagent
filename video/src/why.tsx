// 23-38 s. Why this exists, told with aircraft on an airport diagram (not phones): one shared frequency, a
// half-duplex radio, a stepped-on "hold short", a runway incursion; then the same moment with Unstep listening.
import React from "react";
import {AbsoluteFill, Easing, interpolate} from "remotion";
import {Heli, K, Plane, Sub, Tower, b612, mono, ramp, fadeOut, useT} from "./ui";

export const W0 = 23, W1 = 38;
const RWY_Y = 450, TWY_Y = 640, B1X = 360, HOLD_Y = 556;
const TOWER = {x: 1640, y: 790}, HELI = {x: 1000, y: TWY_Y}, UNSTEP = {x: 1180, y: 790};

const lerp = (t: number, pts: [number, number][]) =>
  interpolate(t, pts.map((p) => p[0]), pts.map((p) => p[1]), {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.inOut(Easing.cubic)});

export const Why: React.FC = () => {
  const t = useT();
  if (t < W0 || t > W1 + 0.1) return null;
  const draw = ramp(t, W0, W0 + 1.1);
  // the Cessna: holds, rolls onto the runway at 29, rewinds at 31.5, then holds for good
  const cy = lerp(t, [[29.0, 592], [30.2, RWY_Y], [31.5, RWY_Y], [32.0, 592]]);
  // landing traffic on runway 33: arrives from the west
  const lx = t < 31.5 ? lerp(t, [[28.4, -120], [30.2, B1X - 40]]) : lerp(t, [[31.5, B1X - 40], [32.0, -120], [34.9, -120], [37.6, 1500]]);
  const incursion = t >= 30.2 && t < 31.5;
  const listening = ramp(t, 32.0, 32.6);
  const recovered = t >= 33.2, approved = t >= 33.9, told = t >= 34.5;
  const heardBroken = t >= 25.9 && !told;
  const strip = (sec: number) => 96 + ((Math.min(sec, 30.8) - 23.6) / (30.8 - 23.6)) * (1824 - 96);
  return (
    <AbsoluteFill style={{background: K.bg, opacity: ramp(t, W0, W0 + 0.3) * fadeOut(t, W1 - 0.25)}}>
      <div style={{position: "absolute", left: 96, top: 40, fontFamily: mono, fontSize: 18, color: K.cyan, opacity: draw}}>UP CLOSE · JOB 02 · CATCHING A STEPPED-ON CALL</div>
      {/* the shared frequency */}
      <div style={{position: "absolute", left: 96, top: 92, fontFamily: mono, fontSize: 17, color: K.dim, opacity: draw * fadeOut(t, 31.4)}}>118.700 MHZ · ONE FREQUENCY, ONE VOICE AT A TIME</div>
      <svg width={1920} height={1080} style={{position: "absolute", inset: 0}}>
        <g opacity={draw * fadeOut(t, 31.4)}>
          <line x1={96} y1={190} x2={1824} y2={190} stroke={K.hair} />
          {t >= 24.0 && <rect x={strip(24.0)} y={170} width={Math.max(0, strip(Math.min(t, 27.6)) - strip(24.0))} height={14} fill={K.magenta} />}
          {t >= 25.4 && <rect x={strip(25.4)} y={194} width={Math.max(0, strip(Math.min(t, 30.7)) - strip(25.4))} height={14} fill={K.red} />}
          {t >= 25.5 && <rect x={strip(25.4)} y={164} width={Math.max(0, strip(Math.min(t, 27.6)) - strip(25.4))} height={50} fill="none" stroke={K.red} strokeWidth={2} strokeDasharray="6 5" />}
        </g>
        {t >= 24 && <text x={strip(24.0)} y={158} fill={K.magenta} fontFamily={mono} fontSize={16} opacity={fadeOut(t, 31.4)}>TOWER → CESSNA 1-2-3</text>}
        {t >= 25.4 && <text x={strip(25.4)} y={236} fill={K.red} fontFamily={mono} fontSize={16} opacity={fadeOut(t, 31.4)}>HELICOPTER 4-5-6 KEYS UP · BOTH TRANSMITTING → SQUEAL</text>}

        {/* the airport, drawn like a chart */}
        <g opacity={draw}>
          <rect x={200} y={TWY_Y - 17} width={1520} height={34} fill={K.faint} />
          <rect x={B1X - 17} y={RWY_Y + 30} width={34} height={TWY_Y - RWY_Y - 30} fill={K.faint} />
          <rect x={240} y={RWY_Y - 30} width={1440 * draw} height={60} fill="#101317" stroke={K.ink} strokeWidth={1.5} />
          {Array.from({length: 22}, (_, i) => <rect key={i} x={300 + i * 62} y={RWY_Y - 1.5} width={30} height={3} fill={K.dim} opacity={draw} />)}
          {/* hold-short marking: two solid, two dashed */}
          {[0, 7].map((d) => <rect key={d} x={B1X - 17} y={HOLD_Y + d} width={34} height={3} fill={incursion ? K.red : K.amber} />)}
          {[14, 21].map((d) => [0, 12, 24].map((o) => <rect key={`${d}-${o}`} x={B1X - 17 + o} y={HOLD_Y + d} width={8} height={3} fill={incursion ? K.red : K.amber} />))}
        </g>
        <g fontFamily={mono} fontSize={16} fill={K.dim} opacity={ramp(t, W0 + 0.6, W0 + 1.2)}>
          <text x={252} y={RWY_Y - 44}>RWY 33</text><text x={1610} y={RWY_Y - 44}>RWY 15</text>
          <text x={1650} y={TWY_Y + 44}>TWY B</text><text x={B1X - 46} y={TWY_Y - 26}>B1</text>
          <text x={B1X - 30} y={HOLD_Y + 18} textAnchor="end" fill={incursion ? K.red : K.amber}>HOLD SHORT LINE</text>
        </g>

        {/* listening lines and private line */}
        <g opacity={listening}>
          {[[B1X, cy], [HELI.x, HELI.y], [TOWER.x, TOWER.y - 20]].map(([x, y], i) => (
            <line key={i} x1={UNSTEP.x} y1={UNSTEP.y - 20} x2={x} y2={y} stroke={K.cyan} strokeWidth={1} strokeDasharray="3 6" opacity={0.7} />
          ))}
        </g>
        {told && <line x1={UNSTEP.x} y1={UNSTEP.y - 20} x2={B1X} y2={cy} stroke={K.magenta} strokeWidth={3}
          strokeDasharray={1200} strokeDashoffset={1200 * (1 - ramp(t, 34.5, 35.1))} />}
        {/* the tower's call, then the helicopter's */}
        {t >= 24.0 && t < 27.8 && <path d={`M${TOWER.x},${TOWER.y - 34} Q ${(TOWER.x + B1X) / 2},${380} ${B1X},${cy - 30}`} stroke={K.magenta} strokeWidth={2}
          fill="none" strokeDasharray="10 8" strokeDashoffset={-t * 60} opacity={fadeOut(t, 27.4)} />}
        {t >= 25.4 && t < 28.2 && <path d={`M${HELI.x},${HELI.y - 30} Q ${HELI.x - 80},${420} ${(TOWER.x + B1X) / 2 - 40},${380}`} stroke={K.red} strokeWidth={2}
          fill="none" strokeDasharray="10 8" strokeDashoffset={-t * 60} opacity={fadeOut(t, 27.8)} />}

        <Tower x={TOWER.x} y={TOWER.y} color={approved ? K.green : K.ink} />
        <Heli x={HELI.x} y={HELI.y} spin={t * 900} color={t >= 25.4 && t < 28 ? K.red : K.ink} />
        <Plane x={B1X} y={cy} color={incursion ? K.red : told ? K.green : K.ink} />
        {(t >= 28.4) && <Plane x={lx} y={RWY_Y} rot={90} s={2.2} color={incursion ? K.red : K.ink} />}
        {incursion && <circle cx={B1X} cy={RWY_Y} r={60 + 10 * Math.sin(t * 14)} fill="none" stroke={K.red} strokeWidth={3} />}

        <g fontFamily={mono} fontSize={16} fill={K.ink}>
          <text x={TOWER.x + 30} y={TOWER.y - 10}>TOWER</text>
          <text x={HELI.x - 70} y={HELI.y + 52}>HELICOPTER 4-5-6</text>
          <text x={B1X + 40} y={cy + 6}>CESSNA 1-2-3</text>
          {incursion && <text x={B1X + 90} y={RWY_Y + 74} fill={K.red} fontSize={22} fontWeight={700}>RUNWAY INCURSION · LANDING TRAFFIC</text>}
        </g>
      </svg>

      {/* what the Cessna heard */}
      {t >= 24.3 && (
        <div style={{position: "absolute", left: 96, top: 290, opacity: fadeOut(t, W1 - 0.4)}}>
          <div style={{fontFamily: mono, fontSize: 16, color: K.dim}}>{told ? "WHAT THE CESSNA HEARS, FROM UNSTEP" : "WHAT THE CESSNA HEARD"}</div>
          <div style={{fontFamily: mono, fontSize: 34, fontWeight: 700, marginTop: 8, color: told ? K.green : K.ink}}>
            {told ? "“HOLD SHORT RUNWAY 33” — READ BACK ✓"
              : heardBroken ? <>CESSNA 1-2-3, <span style={{color: K.red}}>████ █████</span> RUNWAY 3<span style={{color: K.red}}>█</span></>
              : "CESSNA 1-2-3, HOLD SHO".slice(0, Math.max(0, Math.floor((t - 24.3) * 14)))}
          </div>
        </div>
      )}

      {/* Unstep */}
      <div style={{position: "absolute", left: UNSTEP.x - 50, top: UNSTEP.y - 20, opacity: listening, display: "flex", gap: 18, alignItems: "flex-start"}}>
        <div style={{display: "inline-block", border: `1.5px solid ${K.cyan}`, padding: "8px 14px", fontFamily: mono, fontWeight: 700, fontSize: 18, color: K.cyan, background: K.bg}}>UNSTEP</div>
        <div style={{fontFamily: mono, fontSize: 15, lineHeight: 1.55, width: 340}}>
          <div style={{color: recovered ? K.magenta : K.dim}}>{recovered ? "RECOVERED: HOLD SHORT RUNWAY 33" : "LISTENING TO EVERY RADIO"}</div>
          {approved && <div style={{color: K.green}}>CONTROLLER APPROVED</div>}
          {told && <div style={{color: K.magenta}}>SENT TO CESSNA 1-2-3 ONLY</div>}
        </div>
      </div>

      <Sub t={t} from={23.6} to={27.3} tag="HOW A CALL GETS LOST" text="Everyone shares one radio channel. The tower tells the Cessna “hold short”: stop before the runway." />
      <Sub t={t} from={27.4} to={30.3} text={<>Two people talk at once: everyone else hears a squeal, and <b style={{fontWeight: 700}}>neither speaker knows.</b></>} />
      <Sub t={t} from={30.4} to={31.9} text="The Cessna never hears “hold short”, and rolls onto the runway." />
      <Sub t={t} from={32.1} to={37.6} tag="WITH UNSTEP" tagColor={K.cyan} text="Unstep listens for the controller, recovers the lost words and, once the controller approves, tells only that pilot." />
    </AbsoluteFill>
  );
};
