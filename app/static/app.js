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
let speaking = false;  // a speech line is being "spoken"
const speechQueue = [];

function refreshHead() {
  head.setState(speaking ? "talking" : busy ? "thinking" : "idle");
  stage.dataset.working = String(busy && !speaking);
  $("feed").dataset.busy = String(busy);
}

function speak(text) {
  speechQueue.push(text);
  if (!speaking) playNext();
}

function playNext() {
  const text = speechQueue.shift();
  if (text === undefined) {
    speaking = false;
    refreshHead();
    return;
  }
  speaking = true;
  refreshHead();
  const bubble = $("speech");
  $("speech-text").textContent = text;
  bubble.hidden = false;
  bubble.classList.remove("enter", "stale");
  void bubble.offsetWidth; // restart the pop animation
  bubble.classList.add("enter");
  // Rough speaking time from text length. Later: the length of real TTS audio.
  const ms = Math.min(7000, Math.max(1600, 700 + text.length * 48));
  setTimeout(playNext, ms);
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
let socket = null;

function setInputEnabled(on) {
  input.disabled = !on;
  sendBtn.disabled = !on;
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
  $("speech").classList.add("stale"); // fade the previous reply while Matey works
  input.value = "";
  busy = true;
  setInputEnabled(false);
  refreshHead();
});

// ------------------------------------------------------------------ socket
const handlers = {
  hello(e) {
    $("feed-models").textContent = `Brain model: ${e.brain_model}. Voice model: ${e.voice_model}. Version ${e.version}.`;
    setInputEnabled(true);
  },
  status(e) {
    busy = e.state !== "idle";
    refreshHead();
  },
  say(e) { speak(e.text); },
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
