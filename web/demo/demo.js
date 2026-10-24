// Unstep demo screen.
//
// Renders what the gateway's read-only observer feed carries (every word, number
// and highlight comes from a real message) and paces nothing itself: the presenter
// process drives scenes over /demo/events. Vanilla ES module, no build step.

// ---------------------------------------------------------------- constants

const $ = (selector) => document.querySelector(selector);
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
const wsBase = `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}`;

const LANE_COLORS = {
  TOWER: '#8B9AAB',
  PILOT: '#A5B4FC',
  UNSTEP: '#22D3EE',
  CONTROLLER: '#34D399',
};

const PARTY_LANES = {
  tower: 'TOWER',
  radio: 'PILOT',
  pilot: 'PILOT',
  pilot_ear: 'UNSTEP',
  controller: 'CONTROLLER',
  controller_ear: 'CONTROLLER',
};

// Audit stages that carry a transmission (something said or heard).
const SPOKEN_STAGES = new Set([
  'speech',
  'controller_spoken',
  'controller_heard',
  'readback',
  'tower_audio',
  'radio_input',
  'pilot_input',
]);

// Per-step measurements only; nothing here includes presenter pauses.
const LATENCY_ORDER = [
  'detector frame',
  'cockpit STT finalize',
  'Moss search',
  'TTS first audio',
  'readback verdict',
  'LLM first token',
];

const KEY_ACTIONS = {
  ' ': 'next',
  ArrowRight: 'next',
  ArrowLeft: 'prev',
  b: 'prev',
  a: 'mode',
  r: 'replay',
  '0': 'reset',
};

const COUNT_MS = 350;
const TYPE_MS = 400;

// ---------------------------------------------------------------- state

const view = {
  scene: 0,
  generation: null,
  mode: 'REPLAY',
  busy: false,
  services: {},
  observerConnected: false,
  eventsConnected: false,
};

const session = {
  seen: new Set(),
  proposals: new Map(),
  tower: null,
  overlap: null,
  towerItem: null,
  receivedItem: null,
  metrics: new Map(),
  activity: new Map(),
};

const audio = {
  context: null,
  source: null,
  queue: [],
  playing: false,
  epoch: 0,
  enabled: false,
  current: null,
  currentStart: 0,
  last: null,
};

let statsEpoch = 0;

// ---------------------------------------------------------------- DOM helpers

function setText(node, value) {
  node.textContent = value ?? '';
}

function element(tag, value, className) {
  const node = document.createElement(tag);
  setText(node, value);
  if (className) {
    node.className = className;
  }
  return node;
}

function countUp(node, end, suffix = '') {
  if (!Number.isFinite(end)) {
    return;
  }
  const decimals = Number.isInteger(end) ? 0 : 2;
  const start = performance.now();
  function tick(now) {
    const progress = reducedMotion ? 1 : Math.min(1, (now - start) / COUNT_MS);
    setText(node, `${(end * progress).toFixed(decimals)}${suffix}`);
    if (progress < 1) {
      requestAnimationFrame(tick);
    }
  }
  requestAnimationFrame(tick);
}

function scrollToNewest(container) {
  requestAnimationFrame(() => {
    container.scrollTop = container.scrollHeight;
  });
}

// ---------------------------------------------------------------- words and timing

// Readable text for the screen; the phonetic speech text is only a fallback.
function displayTextOf(payload) {
  return payload.display_text || payload.spoken_text || payload.heard_text || payload.answer || '';
}

function tokens(text) {
  return text.split(/\s+/).filter(Boolean);
}

// Word timestamps belong to the spoken text. When the screen shows different
// words, highlight by fraction of the speech time instead of token by token.
function timingFor(displayText, payload) {
  const words = payload.words || [];
  if (!words.length) {
    return { mode: 'none', words };
  }
  const spoken = payload.spoken_text || '';
  const exact = displayText === spoken && tokens(displayText).length === words.length;
  return {
    mode: exact ? 'exact' : 'proportional',
    words,
    start: words[0].start,
    end: words[words.length - 1].end,
  };
}

function renderWords(node, text, timing) {
  node.replaceChildren();
  const parts = tokens(text);
  parts.forEach((part, index) => {
    const span = element('span', part);
    if (timing.mode === 'exact') {
      span.dataset.start = timing.words[index].start;
      span.dataset.end = timing.words[index].end;
    }
    node.append(span);
    if (index < parts.length - 1) {
      node.append(' ');
    }
  });
}

function activeWordIndex(timing, wordCount, seconds) {
  if (timing.mode === 'exact') {
    return timing.words.findIndex((word) => seconds >= word.start && seconds < word.end);
  }
  if (timing.mode !== 'proportional' || seconds < timing.start || seconds >= timing.end) {
    return -1;
  }
  const fraction = (seconds - timing.start) / Math.max(0.001, timing.end - timing.start);
  return Math.min(wordCount - 1, Math.floor(fraction * wordCount));
}

function highlightWords(node, index) {
  node.querySelectorAll('span').forEach((span, position) => {
    span.classList.toggle('active-word', position === index);
  });
}

function highlightLoop() {
  const item = audio.current;
  if (item && audio.context) {
    const seconds = audio.context.currentTime - audio.currentStart;
    const index = activeWordIndex(item.timing, tokens(item.text).length, seconds);
    highlightWords(item.transcript, index);
    highlightWords($('#caption'), index);
  }
  requestAnimationFrame(highlightLoop);
}

// ---------------------------------------------------------------- waveform

function drawWave(canvas, buffer, color) {
  const ctx = canvas.getContext('2d');
  const { width, height } = canvas;
  ctx.clearRect(0, 0, width, height);
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  const data = buffer?.getChannelData(0);
  if (!data) {
    ctx.moveTo(0, height / 2);
    ctx.lineTo(width, height / 2);
  } else {
    for (let x = 0; x < width; x += 3) {
      const from = Math.floor((x / width) * data.length);
      const to = Math.floor(((x + 3) / width) * data.length);
      let peak = 0;
      for (let i = from; i < to; i++) {
        peak = Math.max(peak, Math.abs(data[i]));
      }
      const size = Math.max(1, peak * height * 0.48);
      ctx.moveTo(x, height / 2 - size);
      ctx.lineTo(x, height / 2 + size);
    }
  }
  ctx.stroke();
}

// ---------------------------------------------------------------- timeline lanes

function laneFor(party) {
  return PARTY_LANES[party] || 'UNSTEP';
}

// Newest transmission per lane at full size, older ones compact.
function markNewest(container) {
  const items = container.querySelectorAll('.transmission');
  items.forEach((node, index) => {
    node.classList.toggle('older', index < items.length - 1);
  });
}

function addTransmission(payload, audit) {
  const lane = laneFor(payload.party);
  const node = element('div', null, 'transmission');
  const canvas = element('canvas');
  canvas.width = 900;
  canvas.height = 30;
  const transcript = element('div', null, 'transcript');
  node.append(canvas, transcript);
  drawWave(canvas, null, LANE_COLORS[lane]);

  const text = displayTextOf(payload);
  const item = { payload, audit, lane, node, canvas, transcript, text, timing: timingFor(text, payload), buffer: null };
  renderWords(transcript, item.text, item.timing);

  const container = $(`[data-lane="${lane}"] .transmissions`);
  container.append(node);
  markNewest(container);
  // Every lane may have shrunk to make room, so keep each one at its newest.
  document.querySelectorAll('.transmissions').forEach(scrollToNewest);

  if (audit.stage === 'tower_audio') {
    session.towerItem = item;
  }
  if (audit.stage === 'radio_input') {
    session.receivedItem = item;
    if (!reducedMotion) {
      node.classList.add('shake');
    }
  }
  markBlocked();
  return item;
}

// The pilot lane shows what the cockpit actually received once STT finalizes.
function showReceived(heardText) {
  const item = session.receivedItem;
  if (!item || !heardText) {
    return;
  }
  item.text = heardText;
  item.timing = { mode: 'none', words: [] };
  renderWords(item.transcript, item.text, item.timing);
  if (audio.current === item) {
    renderWords($('#caption'), item.text, item.timing);
  }
}

function placeBand(item, startMs, durationMs) {
  if (!item || !session.overlap || durationMs <= 0) {
    return;
  }
  const { overlap_start: overlapStart, overlap_end: overlapEnd } = session.overlap;
  const left = Math.max(0, Math.min(1, (overlapStart - startMs) / durationMs));
  const right = Math.max(left, Math.min(1, (overlapEnd - startMs) / durationMs));
  let band = item.node.querySelector('.blocked-band');
  if (!band) {
    band = element('div', 'BLOCKED', 'blocked-band');
    item.node.append(band);
    item.node.classList.add('banded');
  }
  band.style.left = `${left * 100}%`;
  band.style.width = `${(right - left) * 100}%`;
}

function strikeBlockedWords(item) {
  const { tower, overlap } = session;
  item.transcript.querySelectorAll('[data-start]').forEach((word) => {
    const start = tower.ptt_start + Number(word.dataset.start) * 1000;
    const end = tower.ptt_start + Number(word.dataset.end) * 1000;
    const covered = Math.max(0, Math.min(end, overlap.overlap_end) - Math.max(start, overlap.overlap_start));
    word.classList.toggle('blocked-word', end > start && covered * 2 >= end - start);
  });
}

// Amber hatched band over the overlap window, on both the tower call and the
// pilot's received audio (which starts at the same instant, ptt_start).
function markBlocked() {
  const { tower, overlap, towerItem, receivedItem } = session;
  if (!tower || !overlap) {
    return;
  }
  if (towerItem) {
    placeBand(towerItem, tower.ptt_start, tower.ptt_end - tower.ptt_start);
    strikeBlockedWords(towerItem);
  }
  if (receivedItem) {
    const decoded = receivedItem.buffer ? receivedItem.buffer.duration * 1000 : 0;
    const duration = decoded || overlap.squelch_close - tower.ptt_start;
    placeBand(receivedItem, tower.ptt_start, duration);
  }
}

// ---------------------------------------------------------------- audio playback

async function unlockAudio() {
  audio.context ||= new AudioContext();
  await audio.context.resume();
  audio.enabled = true;
  $('#start').hidden = true;
  pump();
}

function showCaption(item) {
  const ear = item.lane === 'UNSTEP' ? ' · L / LEFT EAR' : '';
  setText($('#caption-speaker'), `${item.lane}${ear}`);
  $('#caption-speaker').style.color = LANE_COLORS[item.lane];
  renderWords($('#caption'), item.text, item.timing);
  drawWave($('#audio-wave'), item.buffer, LANE_COLORS[item.lane]);
}

function queueSpeech(payload, audit) {
  const item = addTransmission(payload, audit);
  if (!payload.audio_url) {
    showCaption(item);
    return;
  }
  audio.queue.push(item);
  pump();
}

async function decode(item) {
  if (item.buffer) {
    return;
  }
  const response = await fetch(item.payload.audio_url);
  if (!response.ok) {
    throw Error('Audio unavailable');
  }
  item.buffer = await audio.context.decodeAudioData(await response.arrayBuffer());
}

function connectOutput(item) {
  const source = audio.context.createBufferSource();
  source.buffer = item.buffer;
  // The directive voice is left ear only; mono files are panned left here.
  if (item.lane === 'UNSTEP' && item.buffer.numberOfChannels === 1) {
    const pan = audio.context.createStereoPanner();
    pan.pan.value = -1;
    source.connect(pan).connect(audio.context.destination);
  } else {
    source.connect(audio.context.destination);
  }
  return source;
}

async function pump() {
  if (audio.playing || !audio.enabled || !audio.queue.length) {
    return;
  }
  audio.playing = true;
  const epoch = audio.epoch;
  const item = audio.queue.shift();
  audio.last = item;
  try {
    await decode(item);
    if (epoch !== audio.epoch) {
      return;
    }
    drawWave(item.canvas, item.buffer, LANE_COLORS[item.lane]);
    markBlocked();
    audio.source = connectOutput(item);
    audio.current = item;
    audio.currentStart = audio.context.currentTime;
    showCaption(item);
    const ended = new Promise((resolve) => {
      audio.source.onended = resolve;
    });
    audio.source.start();
    await ended;
  } catch (error) {
    if (epoch === audio.epoch) {
      showCaption(item);
      setText($('#status'), 'Audio unavailable; showing transcript.');
    }
  } finally {
    if (epoch === audio.epoch) {
      highlightWords(item.transcript, -1);
      highlightWords($('#caption'), -1);
      audio.current = null;
      audio.source = null;
      audio.playing = false;
      pump();
    }
  }
}

// ---------------------------------------------------------------- latency strip

function recordLatency(label, value) {
  if (!Number.isFinite(value)) {
    return;
  }
  session.metrics.set(label, value);
  renderLatencies();
}

function formatMs(ms) {
  return `${ms.toFixed(ms < 10 ? 2 : 0)} ms`;
}

function renderLatencies() {
  const strip = $('#latencies');
  const live = view.mode === 'LIVE';
  const label = live ? 'MEASURED THIS RUN' : 'OFFLINE FAKES · not real timings';
  strip.replaceChildren(element('span', label, 'strip-label'));
  if (!session.metrics.size) {
    strip.append(element('span', 'Measurements appear as the pipeline runs.'));
    return;
  }
  for (const name of LATENCY_ORDER) {
    if (!session.metrics.has(name)) {
      continue;
    }
    const pill = element('span', `${name} `, 'pill');
    pill.append(element('b', formatMs(session.metrics.get(name))));
    strip.append(pill);
  }
}

function latencyFromAudit(audit, payload) {
  const labels = {
    cockpit_stt: 'cockpit STT finalize',
    local_hint: 'Moss search',
    speech: 'TTS first audio',
    readback: 'readback verdict',
  };
  if (audit.stage === 'detection' && payload.measurement) {
    recordLatency('detector frame', audit.latency_ms);
  }
  if (labels[audit.stage]) {
    recordLatency(labels[audit.stage], audit.latency_ms);
  }
  if (view.services.Moss === 'moss') {
    recordLatency('LLM first token', payload.llm_first_token_ms);
  }
}

// ---------------------------------------------------------------- service status

function markActive(name) {
  session.activity.set(name, Date.now());
}

function renderServices() {
  const connected = view.observerConnected && view.eventsConnected;
  for (const node of document.querySelectorAll('[data-service]')) {
    const name = node.dataset.service;
    const state = view.services[name] || 'idle';
    const recent = Date.now() - (session.activity.get(name) || 0) < 15000;
    const real = !['fake', 'local', 'gateway', 'idle'].includes(state);
    const dot = connected && recent ? '●' : '○';
    node.replaceChildren(
      document.createTextNode(`${dot} ${name}`),
      element('small', `${state}${recent ? ' · activity' : ''}`),
    );
    node.style.color = real && connected && recent ? LANE_COLORS.CONTROLLER : LANE_COLORS.TOWER;
  }
}

// ---------------------------------------------------------------- readback card

// "N123AB" and "Cessna 123" both shown the way they are said: "Cessna 1-2-3".
function spokenCallsign(callsign) {
  if (!callsign) {
    return '-';
  }
  const digits = callsign.replace(/\D/g, '');
  let type = (callsign.match(/^([A-Za-z]+)\s/) || [])[1];
  if (!type && /^N\d/.test(callsign)) {
    type = (session.tower?.text.match(/^([A-Za-z]+)\s/) || [])[1];
  }
  return type && digits ? `${type} ${digits.split('').join('-')}` : callsign;
}

function callsignsMatch(a, b) {
  const da = (a || '').replace(/\D/g, '');
  const db = (b || '').replace(/\D/g, '');
  return Boolean(da && db && (da.includes(db) || db.includes(da)));
}

function readbackRows(heard, expected) {
  return [
    ['CALLSIGN', spokenCallsign(heard?.callsign), spokenCallsign(expected.callsign),
      callsignsMatch(heard?.callsign, expected.callsign)],
    ['ACTION', heard?.action || '-', expected.action, heard?.action === expected.action],
    ['RUNWAY', heard?.runway || '-', expected.runway || '-', (heard?.runway || null) === (expected.runway || null)],
  ];
}

function readbackTable(result, expected) {
  const table = element('table', null, 'readback-table');
  const head = element('tr');
  head.append(element('th', ''), element('th', 'HEARD'), element('th', 'EXPECTED'));
  table.append(head);
  for (const [label, heardValue, expectedValue, matched] of readbackRows(result.slots, expected)) {
    const row = element('tr');
    const heardCell = element('td', `${matched ? '✓' : '✕'} ${heardValue}`, matched ? 'cell-ok' : 'cell-bad flash');
    row.append(element('th', label), heardCell, element('td', expectedValue));
    table.append(row);
  }
  return table;
}

function renderReadback(result) {
  const expected = session.proposals.get(result.event_id)?.slots;
  const verdict = result.match ? 'correct' : 'incorrect';
  const block = element('div', null, 'attempt');
  block.append(element('div', `${result.match ? '✓' : '✕'} Attempt ${result.attempt} · ${verdict}`,
    `attempt-label ${result.match ? 'good' : 'bad'}`));
  if (expected) {
    block.append(readbackTable(result, expected));
  } else {
    block.append(element('div', `Heard: ${result.readback_text}`, 'mono'));
  }
  $('#readback-history').append(block);
  scrollToNewest($('#readback'));
}

// ---------------------------------------------------------------- hint and ground cards

function renderHint(event) {
  const hint = event.local_hint;
  setText($('#hint-text'), hint.text || 'No restrictive hint');
  setText($('#hint-status'), 'Awaiting controller');
  $('#hint-status').className = 'pending';
  const source = `${hint.source_doc_id || 'No source'}${hint.source_text ? ' · ' + hint.source_text : ''}`;
  setText($('#hint-source'), source);
  countUp($('#moss-time'), hint.moss_ms, ' ms · Moss search');
  $('#hint').classList.add('ready');
  markActive('Moss');
}

function renderProposal(proposal) {
  $('#proposal').replaceChildren(
    element('p', `${proposal.confidence.toUpperCase()} · ${proposal.confidence_method}`),
    element('p', `Blocked: ${proposal.blocked_words.join(' ') || 'not identified'}`),
    element('p', proposal.rule_citation || 'No rule citation supplied · mock ground agents'),
  );
}

function renderRejection(directive) {
  setText($('#approval'), `✕ Rejected via ${directive.rejected_via} · directive not sent`);
  $('#approval').className = 'warn';
  setText($('#hint-status'), 'Rejected · pilot told to request say again');
  $('#hint-status').className = 'warn';
}

function renderApproval(directive) {
  const recorded = session.controllerRecorded ? ' (recorded controller clip)' : '';
  setText($('#approval'), `✓ Approved via ${directive.approved_via}${recorded}`);
  $('#approval').className = 'good';
  setText($('#hint-status'), '✓ Controller approved');
  $('#hint-status').className = 'good';
}

// ---------------------------------------------------------------- analytics card

function statTotals(rows) {
  const totals = { blocked: 0, errors: 0, voice: 0 };
  for (const row of rows) {
    const count = Number(row.count) || 0;
    if (row.type === 'AnomalyEvent') {
      totals.blocked += count;
    } else if (row.type === 'ReadbackResult') {
      totals.errors += count;
    } else if (row.type === 'ApprovedDirective' && row.approved_via === 'voice') {
      totals.voice += count;
    }
  }
  return totals;
}

function typeOut(node, text, epoch) {
  const start = performance.now();
  function step(now) {
    if (epoch !== statsEpoch) {
      return;
    }
    const progress = reducedMotion ? 1 : Math.min(1, (now - start) / TYPE_MS);
    setText(node, text.slice(0, Math.ceil(progress * text.length)));
    if (progress < 1) {
      requestAnimationFrame(step);
    }
  }
  requestAnimationFrame(step);
}

function renderStats(result, epoch) {
  const totals = statTotals(result.rows);
  const tiles = [
    ['Blocked calls', totals.blocked],
    ['Readback errors', totals.errors],
    ['Approved by voice', totals.voice],
  ];
  $('#stats-rows').replaceChildren();
  for (const [label, value] of tiles) {
    const tile = element('div', null, 'stat');
    const number = element('b', '0');
    tile.append(number, element('span', label));
    $('#stats-rows').append(tile);
    countUp(number, value);
  }
  const source = result.source === 'elastic' ? 'Elastic ES|QL' : 'Gateway history, Elastic not configured';
  setText($('#stats-source'), source);
  typeOut($('#esql'), result.esql, epoch);
}

async function loadStats() {
  const epoch = ++statsEpoch;
  $('#analytics').hidden = false;
  $('#ground').classList.add('analytics');
  scrollToNewest($('#readback'));
  setText($('#stats-source'), 'Querying analytics…');
  try {
    const response = await fetch('/demo/stats');
    if (!response.ok) {
      throw Error('Analytics unavailable');
    }
    const result = await response.json();
    if (epoch !== statsEpoch) {
      return;
    }
    markActive('Elastic');
    renderStats(result, epoch);
  } catch (error) {
    setText($('#stats-source'), 'Analytics unavailable. No substituted result.');
  }
}

// ---------------------------------------------------------------- observer messages

function isDuplicate(envelope) {
  const signature = JSON.stringify(envelope);
  if (session.seen.has(signature)) {
    return true;
  }
  session.seen.add(signature);
  if (session.seen.size > 1500) {
    session.seen.delete(session.seen.values().next().value);
  }
  return false;
}

function handleAudit(audit) {
  const payload = audit.payload || {};
  latencyFromAudit(audit, payload);
  if (['speech', 'controller_spoken', 'cockpit_stt', 'readback'].includes(audit.stage)) {
    markActive('Cartesia');
  }
  if (['local_hint', 'pilot_query'].includes(audit.stage)) {
    markActive('Moss');
  }
  if (audit.stage === 'cockpit_stt') {
    showReceived(payload.heard_text);
  }
  if (SPOKEN_STAGES.has(audit.stage)) {
    queueSpeech(payload, audit);
  }
}

function handleMessage(envelope) {
  if (isDuplicate(envelope)) {
    return;
  }
  const data = envelope.data || {};
  switch (envelope.type) {
    case 'TowerTranscript':
      session.tower = data;
      setText($('#frequency'), data.frequency);
      setText($('#callsign'), data.callsign);
      markBlocked();
      break;
    case 'AnomalyEvent':
      session.overlap = data;
      renderHint(data);
      markBlocked();
      break;
    case 'ProposedDirective':
      session.proposals.set(data.event_id, data);
      renderProposal(data);
      break;
    case 'ApprovedDirective':
      renderApproval(data);
      break;
    case 'RejectedDirective':
      renderRejection(data);
      break;
    case 'ReadbackResult':
      renderReadback(data);
      break;
    case 'AuditRecord':
      handleAudit(data);
      break;
    default:
      break;
  }
}

// ---------------------------------------------------------------- reset

function stopAudio() {
  audio.epoch++;
  audio.queue = [];
  audio.source?.stop();
  audio.source = null;
  audio.playing = false;
  audio.current = null;
  audio.last = null;
}

function resetView() {
  stopAudio();
  session.seen.clear();
  session.proposals.clear();
  session.metrics.clear();
  session.tower = null;
  session.overlap = null;
  session.towerItem = null;
  session.receivedItem = null;
  document.querySelectorAll('.transmissions').forEach((node) => node.replaceChildren());
  $('#readback-history').replaceChildren();
  setText($('#hint-text'), 'Awaiting radio');
  setText($('#hint-source'), '');
  setText($('#hint-status'), '');
  setText($('#moss-time'), '');
  setText($('#proposal'), 'Awaiting event');
  setText($('#approval'), '');
  $('#analytics').hidden = true;
  $('#ground').classList.remove('analytics');
  $('#hint').classList.remove('ready');
  renderLatencies();
}

// ---------------------------------------------------------------- presenter state

function applyState(data) {
  if (view.generation !== null && data.generation !== view.generation) {
    resetView();
  }
  view.generation = data.generation;
  const previous = view.scene;
  view.scene = data.scene;
  view.busy = data.busy;
  view.services = data.services;
  if (view.mode !== data.mode) {
    view.mode = data.mode;
    renderLatencies();
  }

  document.body.classList.toggle('audio-mode', data.audio_mode);
  if (!data.audio_mode) {
    // Hidden lanes cannot scroll; bring each to its newest once shown.
    document.querySelectorAll('.transmissions').forEach(scrollToNewest);
  }
  document.body.classList.toggle('closing', view.scene === 7);
  $('#close').hidden = view.scene !== 7;
  setText($('#counter'), `${view.scene} / ${data.total}`);
  setText($('#mode'), data.mode);
  setText($('#frequency'), data.frequency);
  setText($('#callsign'), data.callsign);
  session.controllerRecorded = Boolean(data.controller_recorded);
  const fallbacks = data.fallbacks.length ? ' · ' + data.fallbacks.join('; ') : '';
  setText($('#status'), `${data.title} · ${data.status}${fallbacks}`);
  $('#status').title = $('#status').textContent;

  if (view.scene === 6 && previous !== 6) {
    loadStats();
  }
  if (data.action === 'replay' && audio.last) {
    audio.queue.unshift(audio.last);
    pump();
  }
}

async function control(action) {
  try {
    await unlockAudio();
    if (action === 'next' && view.busy) {
      setText($('#status'), 'Still processing this scene. Wait for "Ready".');
      return;
    }
    const response = await fetch('/demo/control', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    });
    if (!response.ok) {
      const result = await response.json();
      setText($('#status'), result.detail || 'Control failed');
    }
  } catch (error) {
    setText($('#status'), 'Presenter disconnected. Reconnecting…');
  }
}

// ---------------------------------------------------------------- sockets

function setConnected(kind, value) {
  if (kind === 'observer') {
    view.observerConnected = value;
  } else {
    view.eventsConnected = value;
  }
  setText($('#connection'), value ? '● observer connected' : '○ reconnecting');
}

function connect(path, handler, kind) {
  const socket = new WebSocket(wsBase + path);
  socket.onopen = () => setConnected(kind, true);
  socket.onmessage = (event) => {
    try {
      handler(JSON.parse(event.data));
    } catch (error) {
      setText($('#status'), 'Could not render gateway message');
    }
  };
  socket.onclose = () => {
    setConnected(kind, false);
    setTimeout(() => connect(path, handler, kind), 1500);
  };
  socket.onerror = () => socket.close();
}

// ---------------------------------------------------------------- keyboard and buttons

function toggleHelp() {
  const dialog = $('#help');
  if (dialog.open) {
    dialog.close();
  } else {
    dialog.showModal();
  }
}

function onKey(event) {
  if (event.repeat || event.ctrlKey || event.metaKey || event.altKey) {
    return;
  }
  if (event.key === '?') {
    event.preventDefault();
    toggleHelp();
    return;
  }
  if ($('#help').open) {
    return;
  }
  const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
  const action = KEY_ACTIONS[key];
  if (action) {
    event.preventDefault();
    control(action);
  }
}

function bindControls() {
  $('#help-button').onclick = toggleHelp;
  $('#help-close').onclick = toggleHelp;
  $('#start').onclick = () => control(view.scene === 0 ? 'next' : 'replay');
  document.querySelectorAll('[data-action]').forEach((button) => {
    button.onclick = () => control(button.dataset.action);
  });
  document.addEventListener('keydown', onKey);
}

function tickClock() {
  setText($('#clock'), new Date().toISOString().slice(11, 19) + 'Z');
  renderServices();
}

// ---------------------------------------------------------------- start

bindControls();
renderLatencies();
connect('/ws/observer', handleMessage, 'observer');
connect('/demo/events', applyState, 'events');
setInterval(tickClock, 1000);
requestAnimationFrame(highlightLoop);
