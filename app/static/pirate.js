// Matey's pixel-art head, drawn as SVG rectangles from text maps.
// Each character in a map is one pixel; the legend maps characters to colours.
// Animation frames (mouth, eye, brow) are small overlays toggled on top of the base.

const PALETTE = {
  R: "#c2412d", // bandana
  r: "#8e2a1c", // bandana shade
  W: "#f6efe2", // white (dots, eye glint, teeth)
  S: "#e2a877", // skin
  s: "#b97e52", // skin shade
  K: "#1d1410", // patch, pupil
  B: "#3b2416", // beard
  b: "#62402a", // beard highlight
  G: "#e8b43c", // gold earring
  M: "#5b1a12", // mouth
};

const BASE = [
  "........................",
  "........RRRRRRRR........",
  "......RRRRRWRRRRRR......",
  ".....RRWRRRRRRRRWRR.....",
  "....RRRRRRRRRRRRRRRRR...",
  "....rrrrrrrrrrrrrrrrrRRr",
  "....SSSSSSSSKKSSSSSSS.Rr",
  "...SSSSSSSKKSSSSSSSSS.rR",
  "...SSSSSKKSSSSBBBSSSS..r",
  "...SSKKKKSSSSSKWSSSSSs..",
  "...SKKKKKSSSSSKKSSSSSss.",
  "...SSKKKSSSSSSSSSSSSSss.",
  "...SSSSSSSSssSSSSSSSSG..",
  "...SSSSSSSsSSsSSSSSSSGG.",
  "...SSBBBBBBBBBBBBBBBBS..",
  "...SBBBbBBBBBBBBBbBBBS..",
  "...BBBBBBBBBBBBBBBBBBB..",
  "....BBBbBBBBBBBBBBbBBB..",
  "....BBBBBBBBBBBBBBBBBB..",
  ".....BBBBBbBBBBBBBBBB...",
  "......BBBBBBBBBBBBBB....",
  "........BBBBBBBBBB......",
  "..........BBBBBB........",
  "........................",
];

// Overlays: lists of [row, col, colourKey].
const span = (row, from, to, key) =>
  Array.from({ length: to - from + 1 }, (_, i) => [row, from + i, key]);

const OVERLAYS = {
  "mouth-closed": [...span(15, 10, 13, "M")],
  "mouth-open": [...span(15, 10, 13, "W"), ...span(16, 9, 14, "M")],
  "mouth-wide": [...span(15, 10, 13, "W"), ...span(16, 9, 14, "M"), ...span(17, 10, 13, "M")],
  "eye-blink": [...span(9, 14, 15, "S"), ...span(10, 14, 15, "K")],
  "brow-raised": [...span(8, 14, 16, "S"), ...span(7, 13, 15, "B"), [9, 14, "W"], [9, 15, "K"]],
};

function rects(cells) {
  return cells
    .map(([y, x, k]) => `<rect x="${x}" y="${y}" width="1.02" height="1.02" fill="${PALETTE[k]}"/>`)
    .join("");
}

function baseCells() {
  const cells = [];
  BASE.forEach((row, y) =>
    [...row].forEach((ch, x) => {
      if (PALETTE[ch]) cells.push([y, x, ch]);
    })
  );
  return cells;
}

export class PirateHead {
  constructor(container) {
    const groups = Object.entries(OVERLAYS)
      .map(([name, cells]) => `<g data-part="${name}" hidden>${rects(cells)}</g>`)
      .join("");
    container.innerHTML =
      `<svg class="head-svg" viewBox="0 0 24 24" shape-rendering="crispEdges" role="img" aria-label="Matey, a pixel-art pirate">` +
      `${rects(baseCells())}${groups}</svg>`;
    this.root = container;
    this.svg = container.querySelector("svg");
    this.mouth = "mouth-closed";
    this.state = "idle";
    this._show("mouth-closed", true);
    this._scheduleBlink();
  }

  _show(part, on) {
    const g = this.svg.querySelector(`[data-part="${part}"]`);
    if (g) g.hidden = !on;
  }

  _setMouth(name) {
    if (name === this.mouth) return;
    this._show(this.mouth, false);
    this._show(name, true);
    this.mouth = name;
  }

  _scheduleBlink() {
    setTimeout(() => {
      if (this.state !== "thinking") {
        this._show("eye-blink", true);
        setTimeout(() => this._show("eye-blink", false), 140);
      }
      this._scheduleBlink();
    }, 2500 + Math.random() * 3000);
  }

  // state: "idle" | "thinking" | "talking"
  setState(state) {
    if (state === this.state) return;
    this.state = state;
    this.root.dataset.state = state;
    this._show("brow-raised", state === "thinking");
    clearInterval(this._flap);
    if (state === "talking") {
      // Mouth flaps at a speech-ish rhythm. Later this can follow real audio.
      const frames = ["mouth-open", "mouth-wide", "mouth-closed", "mouth-open", "mouth-closed"];
      let i = 0;
      this._flap = setInterval(() => this._setMouth(frames[i++ % frames.length]), 110);
    } else {
      this._setMouth("mouth-closed");
    }
  }
}
