// Matey front end: one WebSocket in, everything else is drawing what it says.
import { PirateHead } from "./pirate.js";

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};

// ------------------------------------------------------------------ head + speech
const head = new PirateHead($("head"));
const stage = $("stage");
let busy = false;      // the agent is working on a turn
let speaking = false;  // a speech line is being shown (and played, if it has audio)
const speechQueue = [];  // { text, audio } lines waiting their turn
let stopCurrent = null; // cuts the playing line short (used on disconnect)

// Lines without audio stay up for roughly reading time, within these bounds.
const MIN_DISPLAY_MS = 4000;
const MAX_DISPLAY_MS = 12000;
const MS_PER_CHAR = 60;
// Pause after a spoken line before the next one starts.
const SPEECH_GAP_MS = 500;
// Safety nets so a stalled clip can't hold up the queue forever: a limit on
// getting the clip ready, then its own length plus some slack once it plays.
const AUDIO_LOAD_TIMEOUT_MS = 10000;
const AUDIO_GRACE_MS = 3000;
// A little silence before each clip so the very first syllable isn't clipped.
const AUDIO_LEAD_IN_S = 0.1;
// Let the audio output sleep once Matey has been quiet and idle this long.
const AUDIO_SLEEP_MS = 10000;

// One Web Audio context for the whole page. Kept running while Matey works
// and talks, so the output device is already awake when a line starts.
// (A fresh <audio> element per line made the first line fade in as the
// device powered up from idle.)
let speechOn = false; // set from hello: the server has a TTS voice
let audioCtx = null;
let sleepTimer = null;

async function wakeAudio() { // async so any failure is a rejection, never a throw
  clearTimeout(sleepTimer);
  if (!speechOn) return;
  audioCtx ??= new AudioContext();
  await audioCtx.resume();
}

function sleepAudioSoon() {
  clearTimeout(sleepTimer);
  sleepTimer = setTimeout(() => {
    if (!busy && !speaking) audioCtx?.suspend().catch(() => {});
  }, AUDIO_SLEEP_MS);
}

async function decodeClip(base64) {
  await wakeAudio();
  if (audioCtx?.state !== "running") throw new Error("audio output unavailable");
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
  return audioCtx.decodeAudioData(bytes.buffer);
}

function refreshHead() {
  head.setState(speaking ? "talking" : busy ? "thinking" : "idle");
  stage.dataset.working = String(busy && !speaking);
  $("feed").dataset.busy = String(busy);
}

function speak(line) {
  speechQueue.push({ text: line.text, audio: line.audio });
  if (!speaking) playNext();
}

function displayTime(text) {
  return Math.min(MAX_DISPLAY_MS, Math.max(MIN_DISPLAY_MS, 1000 + text.length * MS_PER_CHAR));
}

function playNext() {
  const line = speechQueue.shift();
  if (line === undefined) {
    speaking = false;
    refreshHead();
    sleepAudioSoon();
    return;
  }
  speaking = true;
  refreshHead();
  const bubble = $("speech");
  $("speech-text").textContent = line.text;
  bubble.hidden = false;
  bubble.classList.remove("enter", "stale");
  void bubble.offsetWidth; // restart the pop animation
  bubble.classList.add("enter");

  // Exactly one of: audio ended, audio failed, watchdog, or timed hold moves the queue on.
  let finished = false;
  let watchdog = null;
  const finish = (delay) => {
    if (finished) return;
    finished = true;
    clearTimeout(watchdog);
    stopCurrent = null;
    setTimeout(playNext, delay);
  };

  if (!line.audio) {
    finish(displayTime(line.text));
    return;
  }
  let source = null;
  stopCurrent = () => {
    source?.stop();
    finish(0);
  };
  watchdog = setTimeout(stopCurrent, AUDIO_LOAD_TIMEOUT_MS);
  decodeClip(line.audio)
    .then((buffer) => {
      if (finished) return; // cut short while decoding
      source = audioCtx.createBufferSource();
      source.buffer = buffer;
      source.connect(audioCtx.destination);
      source.onended = () => finish(SPEECH_GAP_MS);
      source.start(audioCtx.currentTime + AUDIO_LEAD_IN_S);
      clearTimeout(watchdog);
      watchdog = setTimeout(stopCurrent, (AUDIO_LEAD_IN_S + buffer.duration) * 1000 + AUDIO_GRACE_MS);
    })
    .catch(() => finish(displayTime(line.text))); // can't decode or play: show it for reading time
}

function stopSpeech() {
  speechQueue.length = 0;
  stopCurrent?.();
}

// ------------------------------------------------------------------ windows
// One reusable window shell. Each component type only supplies a body renderer.
const deck = $("deck");
const windows = new Map(); // id -> { node, body, component }
let topZ = 10;

const renderers = {
  list(body, component, previous) {
    const before = new Set((previous?.items ?? []).map((i) => i.id));
    const after = new Set(component.items.map((i) => i.id));
    let ul = body.querySelector("ul");
    if (!ul) {
      ul = el("ul", "list");
      body.append(ul);
    }
    // Animate removals: strike through, then drop.
    ul.querySelectorAll("li[data-id]").forEach((li) => {
      if (!after.has(li.dataset.id)) {
        li.classList.add("gone");
        li.removeAttribute("data-id");
        setTimeout(() => li.remove(), 650);
      }
    });
    for (const item of component.items) {
      if (ul.querySelector(`li[data-id="${item.id}"]`)) continue;
      const li = el("li", before.has(item.id) || !previous ? "" : "new", item.text);
      li.dataset.id = item.id;
      ul.append(li);
    }
    let empty = body.querySelector(".list-empty");
    if (component.items.length === 0 && !empty) body.append(el("p", "list-empty", "Nothing on this list yet."));
    if (component.items.length > 0 && empty) empty.remove();
  },
  note(body, component, previous) {
    body.textContent = component.text;
    if (previous && previous.text !== component.text) {
      body.classList.remove("updated");
      void body.offsetWidth; // restart the highlight animation
      body.classList.add("updated");
    }
  },
};

function createShell(component) {
  const node = el("article", `win win--${component.type} enter`);
  node.setAttribute("aria-label", `${component.type}: ${component.title}`);
  const bar = el("div", "win-bar");
  const title = el("span", "win-title", component.title);
  bar.append(title, el("span", "win-id", component.id));
  const body = el("div", "win-body");
  node.append(bar, body);
  deck.append(node);
  const { x, y } = pickSpot(node);
  node.style.left = `${x}px`;
  node.style.top = `${y}px`;
  node.style.zIndex = ++topZ;
  makeDraggable(node, bar);
  return { node, body, title };
}

function upsertWindow(component) {
  let w = windows.get(component.id);
  const previous = w?.component;
  if (!w) {
    w = createShell(component);
    windows.set(component.id, w);
  }
  w.title.textContent = component.title;
  (renderers[component.type] ?? renderers.note)(w.body, component, previous);
  w.component = component;
  if (!previous) requestAnimationFrame(() => {
    // re-place once the body has content and a real height
    const { x, y } = pickSpot(w.node);
    w.node.style.left = `${x}px`;
    w.node.style.top = `${y}px`;
  });
}

function removeWindow(id) {
  const w = windows.get(id);
  if (!w) return;
  windows.delete(id);
  w.node.classList.add("leaving");
  setTimeout(() => w.node.remove(), 260);
}

// Semi-random placement that avoids Matey, the composer and other windows.
function pickSpot(node) {
  const W = window.innerWidth, H = window.innerHeight;
  const w = node.offsetWidth || 250, h = node.offsetHeight || 160;
  const margin = 16;
  const blocked = [stage, $("composer"), $("feed"), document.querySelector(".brand")]
    .map((n) => n.getBoundingClientRect());
  for (const other of windows.values()) if (other.node !== node) blocked.push(other.node.getBoundingClientRect());
  const overlap = (a, b) =>
    Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) *
    Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
  let best = null;
  for (let i = 0; i < 60; i++) {
    const x = margin + Math.random() * Math.max(1, W - w - margin * 2);
    const y = 70 + Math.random() * Math.max(1, H - h - 170);
    const box = { left: x, top: y, right: x + w, bottom: y + h };
    const score = blocked.reduce((s, b) => s + overlap(box, b), 0);
    if (!best || score < best.score) best = { x, y, score };
    if (score === 0) break;
  }
  return best;
}

function makeDraggable(node, handle) {
  node.addEventListener("pointerdown", () => (node.style.zIndex = ++topZ));
  handle.addEventListener("pointerdown", (e) => {
    const startX = e.clientX - node.offsetLeft;
    const startY = e.clientY - node.offsetTop;
    handle.setPointerCapture(e.pointerId);
    const move = (ev) => {
      const x = Math.min(window.innerWidth - 60, Math.max(-node.offsetWidth + 60, ev.clientX - startX));
      const y = Math.min(window.innerHeight - 40, Math.max(0, ev.clientY - startY));
      node.style.left = `${x}px`;
      node.style.top = `${y}px`;
    };
    const up = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", up);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
  });
}

// ------------------------------------------------------------------ activity feed
const feedList = $("feed-list");
const feedEntries = new Map(); // key -> li
let unread = 0;
let feedOpen = false;

function timeStamp(ts) {
  return new Date((ts ?? Date.now() / 1000) * 1000).toLocaleTimeString("en-GB");
}

function detailsBlock(label, text) {
  const d = el("details");
  d.append(el("summary", "", label), el("pre", "", text));
  return d;
}

function feedEvent(e) {
  let li = e.key ? feedEntries.get(e.key) : null;
  const isNew = !li;
  if (isNew) {
    li = el("li");
    const line = el("div");
    line.append(el("span", "text", e.text ?? ""), el("span", "when", timeStamp(e.ts)));
    li.append(line);
    if (e.detail) li.append(detailsBlock(e.tool === "say" ? "Plain message" : "Details", e.detail));
    feedList.prepend(li);
    if (e.key) feedEntries.set(e.key, li);
    $("feed-empty").hidden = true;
  }
  li.dataset.kind = e.kind;
  li.dataset.status = e.status ?? "done";
  if (e.result) li.append(detailsBlock("Result", e.result));
  if (isNew && !feedOpen) {
    unread += 1;
    const badge = $("feed-badge");
    badge.textContent = unread > 99 ? "99+" : unread;
    badge.hidden = false;
    badge.classList.remove("bump");
    void badge.offsetWidth;
    badge.classList.add("bump");
  }
}

$("feed-toggle").addEventListener("click", () => {
  feedOpen = !feedOpen;
  $("feed-panel").hidden = !feedOpen;
  $("feed").dataset.open = String(feedOpen);
  $("feed-toggle").setAttribute("aria-expanded", String(feedOpen));
  if (feedOpen) {
    unread = 0;
    $("feed-badge").hidden = true;
  }
});

$("feed-clear").addEventListener("click", () => {
  feedList.replaceChildren();
  feedEntries.clear();
  $("feed-empty").hidden = false;
});

// ------------------------------------------------------------------ composer
const input = $("message");
const sendBtn = $("send");
const micBtn = $("mic");
let socket = null;

function setInputEnabled(on) {
  input.disabled = !on;
  sendBtn.disabled = !on;
  micBtn.disabled = !on;
  input.placeholder = on ? "Try: add bananas and apples to my shopping list" : "Matey's on it…";
  $("status-text").textContent = on ? "Ready for orders" : busy ? "Working…" : "Connecting…";
  if (on) input.focus();
}

$("composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text || busy || socket?.readyState !== WebSocket.OPEN) return;
  socket.send(JSON.stringify({ type: "user_message", text }));
  $("you-said").textContent = text;
  $("you-said").hidden = false;
  input.value = "";
  startTurn();
});

// Lock the composer while Matey works on the request just sent.
function startTurn() {
  $("speech").classList.add("stale"); // fade the previous reply while Matey works
  wakeAudio().catch(() => {}); // warm up the audio output while Matey thinks (needs this click)
  busy = true;
  setInputEnabled(false);
  refreshHead();
}

// ------------------------------------------------------------------ microphone
// Click to start recording, click again to send it. Shown only when the
// server has speech-to-text (hello.transcription) and the browser allows the
// mic, which needs localhost or HTTPS. The server transcribes the recording
// and runs it as a normal turn, sending the words back as a transcript event.
const MAX_RECORDING_MS = 30000;
let recording = null; // { recorder, chunks, timer, send } while listening

async function startRecording() {
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    feedEvent({ kind: "error", text: `⚠️ Microphone unavailable: ${err.message || err.name}` });
    return;
  }
  if (busy || recording || socket?.readyState !== WebSocket.OPEN) {
    stream.getTracks().forEach((t) => t.stop());
    return;
  }
  const rec = { recorder: new MediaRecorder(stream), chunks: [], send: true };
  rec.recorder.addEventListener("dataavailable", (e) => {
    if (e.data.size) rec.chunks.push(e.data);
  });
  rec.recorder.addEventListener("stop", () => {
    stream.getTracks().forEach((t) => t.stop()); // turns off the browser's recording indicator
    if (rec.send) sendRecording(new Blob(rec.chunks, { type: rec.recorder.mimeType || "audio/webm" }));
  });
  rec.timer = setTimeout(() => stopRecording(true), MAX_RECORDING_MS);
  recording = rec;
  rec.recorder.start();
  micBtn.setAttribute("aria-pressed", "true");
  micBtn.setAttribute("aria-label", "Stop and send");
  input.disabled = true;
  sendBtn.disabled = true;
  input.placeholder = "Listening… click the mic to send";
}

// send=false throws the recording away (used on disconnect).
function stopRecording(send) {
  if (!recording) return;
  clearTimeout(recording.timer);
  recording.send = send;
  recording.recorder.stop();
  recording = null;
  micBtn.setAttribute("aria-pressed", "false");
  micBtn.setAttribute("aria-label", "Speak to Matey");
  if (send) {
    $("you-said").hidden = true; // until the transcript arrives
    startTurn();
  }
}

function sendRecording(blob) {
  if (!blob.size) return voiceFailed("⚠️ Nothing was recorded.");
  const reader = new FileReader();
  reader.onload = () => {
    if (socket?.readyState !== WebSocket.OPEN) return;
    const audio = String(reader.result).split(",")[1]; // drop the "data:...;base64," prefix
    socket.send(JSON.stringify({ type: "voice_message", audio, mime: blob.type }));
  };
  reader.onerror = () => voiceFailed("⚠️ Couldn't read the recording.");
  reader.readAsDataURL(blob);
}

function voiceFailed(text) {
  feedEvent({ kind: "error", text });
  handlers.turn_end();
}

micBtn.addEventListener("click", () => {
  wakeAudio().catch(() => {}); // this click lets the audio output start
  if (recording) stopRecording(true);
  else if (!busy) startRecording();
});

// ------------------------------------------------------------------ socket
const handlers = {
  hello(e) {
    speechOn = Boolean(e.speech);
    const micOn = Boolean(e.transcription && navigator.mediaDevices?.getUserMedia && window.MediaRecorder);
    micBtn.hidden = !micOn;
    const voiceInput = !e.transcription ? "off"
      : micOn ? e.transcription : `${e.transcription}, but this page can't use the mic (needs localhost or HTTPS)`;
    $("feed-models").textContent = `Brain model: ${e.brain_model}. Voice model: ${e.voice_model}. `
      + `Spoken voice: ${e.speech ?? "off"}. Voice input: ${voiceInput}. Version ${e.version}.`;
    setInputEnabled(true);
  },
  status(e) {
    busy = e.state !== "idle";
    refreshHead();
  },
  say(e) { speak(e); },
  transcript(e) {
    $("you-said").textContent = e.text;
    $("you-said").hidden = false;
  },
  ui(e) {
    if (e.op === "upsert") upsertWindow(e.component);
    if (e.op === "delete") removeWindow(e.component_id);
  },
  activity: feedEvent,
  error(e) { feedEvent({ kind: "error", text: `⚠️ ${e.text}`, ts: e.ts }); },
  turn_end() {
    busy = false;
    refreshHead();
    setInputEnabled(true);
    if (!speaking) sleepAudioSoon();
  },
};

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${proto}://${location.host}/ws`);
  socket.addEventListener("open", () => ($("banner").hidden = true));
  socket.addEventListener("message", (msg) => {
    const event = JSON.parse(msg.data);
    handlers[event.type]?.(event);
  });
  socket.addEventListener("close", () => {
    // A new connection is a new conversation, so clear the old windows.
    busy = false;
    stopRecording(false);
    stopSpeech();
    refreshHead();
    setInputEnabled(false);
    for (const id of [...windows.keys()]) removeWindow(id);
    $("banner").textContent = "Lost connection to the Matey server. Retrying every few seconds.";
    $("banner").hidden = false;
    setTimeout(connect, 3000);
  });
}

refreshHead();
connect();
