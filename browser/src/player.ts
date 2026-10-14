// <manimgx-player>: ManimGX's player in the page. The engine's own player, the one `manimgx
// preview`'s window is, compiled to WebAssembly: it draws the film and its face (the controls, the
// time, the plays, captions, the scene's error, the keys) onto a canvas with WebGPU, and keeps the
// clock and the sound. The element only hands it what its viewer does, in the web's own words,
// draws it when it is due, and does what it asks (another scene, full screen). Its scene is
// Python, run in the browser by Pyodide (see director.ts).
//
//   <manimgx-player><script type="text/python"> …a scene… </script></manimgx-player>
//   player.source = code                                    (the film made again, time kept)

import type { Engine, Player } from "./engine.js";
import { message } from "./protocol.js";
import type { Failure, FromDirector, SceneError, ToDirector, Unsupported } from "./protocol.js";

const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/";
const MAC = /Mac|iPhone|iPad/.test(navigator.platform);

/** What the engine needs of a GPU beyond WebGPU itself, in WebGPU's names: float32 targets it
 *  blends (a view adds its coverage in one), and float32 depth with stencil (its reversed-Z
 *  depth). The engine asks its adapter for the same (rust/engine/src/render.rs, `adapter`). */
const FEATURES = ["float32-blendable", "depth32float-stencil8"];

/** Where Pyodide and ManimGX come from (set before the first film starts). */
export const settings = {
  /** Pyodide's files (its `indexURL`). */
  pyodide: PYODIDE,
  /** What micropip installs: `manimgx==<this version>` from PyPI, or a wheel's URL. */
  manimgx: "manimgx",
};

let script: () => string | URL; // the director's script, as `define` was given it

/** The part of WebGPU looked at before anything downloads. */
interface Gpu {
  requestAdapter(options: {
    powerPreference: "high-performance";
  }): Promise<{ readonly features: ReadonlySet<string> } | null>;
}

let checked: Promise<Unsupported | null> | undefined;

/** What this browser lacks to play films, or null if it lacks nothing: WebGPU, a GPU it can draw
 *  with (the one the engine asks for), and what the engine needs of that GPU. Nothing downloads
 *  to find out, and it is found out once for the page. A player finds it out too, before it
 *  downloads Python: a page asks only to know before it makes one. */
export function unsupported(): Promise<Unsupported | null> {
  checked ??= lacking();
  return checked;
}

async function lacking(): Promise<Unsupported | null> {
  const gpu = (navigator as { gpu?: Gpu }).gpu;
  if (!gpu) {
    return { reason: "webgpu", message: "This browser has no WebGPU, which ManimGX draws with." };
  }
  const adapter = await gpu
    .requestAdapter({ powerPreference: "high-performance" })
    .catch(() => null);
  if (!adapter) {
    return { reason: "adapter", message: "WebGPU found no GPU here for ManimGX to draw with." };
  }
  const missing = FEATURES.filter((feature) => !adapter.features.has(feature));
  if (missing.length === 0) return null;
  return {
    reason: "features",
    missing,
    message: `This GPU lacks what ManimGX draws with: WebGPU's ${missing.join(" and ")}.`,
  };
}

/** What the director says to a film's element. */
interface PagePlayer {
  wait(): void;
  feed(bytes: ArrayBuffer): void;
  frame(): void;
  error(error: SceneError): void;
  fail(failure: Failure): void;
}

interface Page {
  players: Map<number, PagePlayer>;
  engine: Promise<Engine | null>;
  status: string;
  failure: Failure | null;
  /** Say it to the director, which exists once the browser is known to play films. */
  send(data: ToDirector): void;
}

// The page's director, its engine (once it is up), and its players. A page that failed is
// forgotten, so a player made later begins again: the download may work now.
let page: Page | undefined;

/** The page's director (Pyodide, in a worker) and engine, begun once: its worker made, and Python
 *  downloaded, only if this browser can play what they make. */
function begin(): Page {
  if (page) return page;
  let director: Worker | undefined;
  const early: ToDirector[] = []; // what the page said before its director was made
  const players = new Map<number, PagePlayer>();
  let up: (engine: Engine | null) => void = () => {};
  const current: Page = {
    players,
    engine: new Promise((resolve) => (up = resolve)),
    status: "", // nothing to say while the browser is checked
    failure: null,
    send: (data) => (director ? director.postMessage(data) : early.push(data)),
  };
  page = current;
  const fail = (failure: Failure): void => {
    if (current.failure !== null) return;
    current.failure = failure;
    current.status = failure.message;
    up(null);
    director?.terminate();
    if (page === current) page = undefined;
    for (const player of [...players.values()]) player.fail(failure);
  };
  const python = (said: string): void => fail({ reason: "python", message: said });
  void unsupported().then((lacks) => {
    if (lacks) return fail(lacks);
    director = new Worker(script(), { type: "module" });
    director.onerror = (event) => python(`ManimGX could not start: ${event.message}`);
    director.onmessageerror = () => python("ManimGX could not read its worker's reply");
    director.onmessage = async ({ data }: MessageEvent<FromDirector>) => {
      if (current.failure !== null) return;
      if ("failure" in data) return python(data.failure);
      if ("status" in data) {
        current.status = data.status;
        for (const player of players.values()) player.wait();
      }
      if ("engine" in data) {
        // the player, from the ManimGX the director installed: its JS, its WebAssembly, the
        // fonts its face is set in
        const { js, wasm, fonts } = data.engine;
        const url = URL.createObjectURL(new Blob([js], { type: "text/javascript" }));
        try {
          const engine = (await import(url)) as Engine;
          await engine.default({ module_or_path: wasm });
          await engine.init(fonts);
          up(engine);
        } catch (error) {
          fail({ reason: "engine", message: `ManimGX can't draw here: ${message(error)}` });
        } finally {
          URL.revokeObjectURL(url);
        }
      }
      if ("film" in data) {
        const player = players.get(data.film);
        if ("feed" in data) player?.feed(data.feed);
        else if ("frame" in data) player?.frame();
        else player?.error(data.error);
      }
    };
    director.postMessage({ boot: { pyodide: settings.pyodide, manimgx: settings.manimgx } });
    for (const data of early.splice(0)) director.postMessage(data);
  });
  return current;
}

let films = 0;

/** A scene written in Python, made in the page and played on a canvas by ManimGX's engine,
 *  with the engine's own controls.
 *
 *  As a media element does, it tells the page how the scene fares: a `loadeddata` event when a
 *  run of the scene has made its first frame, and an `error` event (an `ErrorEvent`) when a run
 *  fails, whose `error` property says why. If it cannot play at all, a `failure` event, whose
 *  `failure` property says why. */
export class ManimgxPlayer extends HTMLElement {
  static observedAttributes = ["scene"];

  #film = 0;
  #canvas: HTMLCanvasElement;
  #said: HTMLParagraphElement;
  #source: string | null = null;
  #error: SceneError | null = null;
  #failure: Failure | null = null;
  #backlog: (() => void)[] = []; // what the director said before the player was up, in order
  #wants: { time: number; playing: boolean | null } = { time: 0, playing: null };
  #begun = false;
  #player: Player | null = null; // native GPU resources belong to one connected lifetime
  #connection: AbortController | undefined;
  #timer: number | undefined;
  #frame = 0;
  #root: ShadowRoot;

  constructor() {
    super();
    this.#root = this.attachShadow({ mode: "open" });
    this.#root.innerHTML = `<style>
      :host { display: block; position: relative; aspect-ratio: var(--film, 16 / 9); background: #000; outline: none; contain: content; }
      canvas { position: absolute; inset: 0; width: 100%; height: 100%; touch-action: pan-y; }
      p { position: absolute; inset: 0; margin: auto; height: 1.5em; text-align: center; color: #fffb; font: 15px system-ui, sans-serif; }
    </style><canvas></canvas><p></p>`;
    const canvas = this.#root.querySelector("canvas");
    const said = this.#root.querySelector("p");
    if (!canvas || !said) throw new Error("The player's canvas and status are missing");
    this.#canvas = canvas;
    this.#said = said; // what it waits for, until the engine is up
  }

  connectedCallback(): void {
    if (!this.hasAttribute("tabindex")) this.tabIndex = 0; // it takes keys
    if (this.#connection || this.#failure !== null) return;
    this.#film = ++films; // late bytes from an earlier connection belong to its old decoder
    const connection = (this.#connection = new AbortController());
    // Begun a task later: a page can still set `settings` after importing this.
    const task = setTimeout(() => {
      if (!connection.signal.aborted) this.#begin(connection.signal);
    });
    connection.signal.addEventListener(
      "abort",
      () => {
        clearTimeout(task);
        clearTimeout(this.#timer);
        cancelAnimationFrame(this.#frame);
        this.#frame = 0;
      },
      { once: true },
    );
  }

  disconnectedCallback(): void {
    this.#connection?.abort();
    this.#connection = undefined;
    if (page?.players.delete(this.#film) && page.failure === null) {
      page.send({ film: this.#film, drop: true });
    }
    this.#backlog = [];
    const player = this.#player;
    if (player) {
      this.#wants = { time: player.time, playing: false };
      player.pause();
      this.#player = null;
      player.free();
    }
  }

  attributeChangedCallback(): void {
    if (this.#begun && this.#source !== null) this.#run();
  }

  /** The scene's Python source: set it, and the film is made again (the time kept). */
  get source(): string | null {
    return this.#source;
  }
  set source(code: string | null) {
    this.#source = code == null ? null : String(code);
    if (this.#begun && this.#source !== null) this.#run();
  }

  /** Why the scene's latest run failed, until a later run makes its first frame; null if it has
   *  not failed. Set before the `error` event, and cleared before `loadeddata`. */
  get error(): SceneError | null {
    return this.#error;
  }

  /** Why it cannot play at all, once it cannot: what the browser lacks, or what failed later.
   *  Null until then; set before the `failure` event. It stays failed: another element tries
   *  again. */
  get failure(): Failure | null {
    return this.#failure;
  }

  /** The scene shown (a file may define several; N and P go through them). Another scene starts
   *  at its beginning. */
  get scene(): string | null {
    return this.#player?.scene ?? this.getAttribute("scene");
  }
  set scene(name: string | null) {
    this.currentTime = 0;
    if (name == null) this.removeAttribute("scene");
    else this.setAttribute("scene", name);
  }

  /** Seconds. */
  get currentTime(): number {
    return this.#player?.time ?? this.#wants.time;
  }
  set currentTime(t: number) {
    if (!Number.isFinite(Number(t))) return;
    if (this.#player) this.#player.time = Number(t);
    else this.#wants.time = Number(t);
    this.#after();
  }
  /** Seconds made so far; NaN before the film's first frame. */
  get duration(): number {
    return this.#player?.film ? this.#player.duration : NaN;
  }
  get paused(): boolean {
    return this.#player
      ? !this.#player.playing
      : !(this.#wants.playing ?? this.hasAttribute("autoplay"));
  }
  play(): void {
    if (this.#player) this.#player.play();
    else this.#wants.playing = true;
    this.#after();
  }
  pause(): void {
    if (this.#player) this.#player.pause();
    else this.#wants.playing = false;
    this.#after();
  }

  // ── the player ─────────────────────────────────────────────────────────────────────────

  async #begin(signal: AbortSignal): Promise<void> {
    if (this.#failure !== null) return;
    if (!this.#begun) {
      this.#begun = true;
      const script = this.querySelector('script[type="text/python"]');
      if (script && this.#source === null) this.#source = dedent(script.textContent);
    }
    const { players, engine } = begin();
    players.set(this.#film, {
      wait: () => this.#wait(),
      feed: (bytes) => this.#feed(bytes),
      frame: () => this.#loaded(),
      error: (error) => this.#broke(error),
      fail: (failure) => this.#fail(failure),
    });
    this.#wait();
    if (this.#source !== null) this.#run();
    const canvas = this.#canvas;
    const box = canvas.getBoundingClientRect();
    const width = Math.max(1, Math.round(box.width * devicePixelRatio));
    const height = Math.max(1, Math.round(box.height * devicePixelRatio));
    if (canvas.width !== width) canvas.width = width;
    if (canvas.height !== height) canvas.height = height;
    // An unattached element must not be retained by the page's pending runtime promise.
    const made = await Promise.race([
      engine,
      new Promise<undefined>((resolve) =>
        signal.addEventListener("abort", () => resolve(undefined), { once: true }),
      ),
    ]);
    if (!made || signal.aborted || this.#failure !== null) return;
    try {
      const { time, playing } = this.#wants;
      this.#player = new made.Player(canvas, time, playing ?? this.hasAttribute("autoplay"), MAC);
      this.#player.resize(canvas.width, canvas.height, devicePixelRatio);
    } catch (error) {
      return this.#stop(error);
    }
    this.#said.remove();
    this.#wire(signal);
    for (const step of this.#backlog.splice(0)) {
      if (signal.aborted) break; // a listener took the element away
      step();
    }
    this.#after();
  }

  #wait(): void {
    if (!this.#player && this.#failure === null && page) this.#said.textContent = page.status;
  }

  /** It cannot play: it says why, and tells the page. */
  #fail(failure: Failure): void {
    this.#failure = Object.freeze(failure);
    this.disconnectedCallback();
    this.#said.textContent = failure.message;
    this.#root.append(this.#said);
    this.dispatchEvent(new Event("failure"));
  }

  /** Its engine failed while it played. */
  #stop(error: unknown): void {
    this.#fail({ reason: "engine", message: `ManimGX stopped: ${message(error)}` });
  }

  #run(): void {
    if (this.#source === null || !page?.players.has(this.#film)) return;
    page.send({
      film: this.#film,
      run: { source: this.#source, scene: this.getAttribute("scene") },
    });
  }

  /** The player, if what the director said (`later`) can be acted on now. Before the player is
   *  up it is kept, to be acted on then in the order it was said: the bytes first, and what the
   *  page hears of them after. */
  #up(later: () => void): Player | null {
    if (this.#failure !== null) return null;
    if (!this.#player) this.#backlog.push(later);
    return this.#player;
  }

  #feed(bytes: ArrayBuffer): void {
    const player = this.#up(() => this.#feed(bytes));
    if (!player) return;
    try {
      player.feed(new Uint8Array(bytes));
    } catch (error) {
      return this.#stop(error);
    }
    // the film's own proportions (unless the page sizes the player itself)
    const film = player.film;
    if (film) this.style.setProperty("--film", `${film[0]} / ${film[1]}`);
    this.#after();
  }

  /** A run has made its first frame: the film is there, and it has not failed (yet). */
  #loaded(): void {
    if (!this.#up(() => this.#loaded())) return;
    this.#error = null;
    this.dispatchEvent(new Event("loadeddata"));
  }

  /** A run failed. The player shows the error over the last picture it has. */
  #broke(error: SceneError): void {
    if (!this.#up(() => this.#broke(error))) return;
    this.#error = Object.freeze(error);
    this.dispatchEvent(
      new ErrorEvent("error", { message: error.message, lineno: error.line ?? 0, error }),
    );
  }

  /** What the viewer does, handed on as the web has it; what the player takes, the page doesn't. */
  #wire(signal: AbortSignal): void {
    const p = this.#player,
      canvas = this.#canvas;
    if (!p) return;
    const at = (e: PointerEvent): [number, number] => {
      const box = canvas.getBoundingClientRect();
      return [
        (e.clientX - box.left) * (canvas.width / box.width),
        (e.clientY - box.top) * (canvas.height / box.height),
      ];
    };
    // an event handed on (while this player is the element's: not after it failed), the default
    // action prevented if the player took it
    const on = <K extends keyof HTMLElementEventMap>(
      target: Pick<HTMLElement, "addEventListener">,
      type: K,
      hand: (event: HTMLElementEventMap[K]) => boolean | void,
      options?: AddEventListenerOptions,
    ): void =>
      target.addEventListener(
        type,
        (e) => {
          if (this.#player !== p) return;
          if (hand(e)) e.preventDefault();
          this.#after();
        },
        { ...options, signal },
      );
    let pressed: number | null = null; // the pointer that pressed: one at a time, its primary button or finger
    on(this, "keydown", (e) => p.key(e.key, e.ctrlKey, e.altKey, e.metaKey));
    on(canvas, "pointermove", (e) => p.pointer(...at(e)));
    on(canvas, "pointerdown", (e) => {
      if (pressed !== null || e.button !== 0 || !e.isPrimary) return false;
      pressed = e.pointerId;
      this.focus({ preventScroll: true });
      canvas.setPointerCapture(e.pointerId);
      return p.press(...at(e), e.pointerType === "touch");
    });
    const end = (e: PointerEvent, ended: () => boolean | void): boolean | void => {
      if (e.pointerId !== pressed) return false;
      pressed = null;
      return ended();
    };
    on(canvas, "pointerup", (e) => end(e, () => p.release()));
    on(canvas, "pointercancel", (e) => end(e, () => p.cancel()));
    on(canvas, "pointerleave", () => p.leave());
    on(
      canvas,
      "wheel",
      (e) => {
        const unit = [1, 20, canvas.clientHeight][e.deltaMode] ?? 1; // pixels, lines (as a window's), pages
        return p.wheel(e.deltaX * unit, e.deltaY * unit);
      },
      { passive: false },
    );
    on(document, "fullscreenchange", () => p.fullscreen(document.fullscreenElement === this));
    // drawn at the size the page shows it, in the screen's own pixels: sharp at any size
    const resize = new ResizeObserver(([entry]) => {
      if (!entry) return;
      const box = entry.devicePixelContentBoxSize?.[0];
      const css = entry.contentBoxSize[0];
      if (!css) return;
      const w = box ? box.inlineSize : Math.round(css.inlineSize * devicePixelRatio);
      const h = box ? box.blockSize : Math.round(css.blockSize * devicePixelRatio);
      if (this.#player !== p) return;
      p.resize(w, h, w / css.inlineSize);
      this.#after();
    });
    resize.observe(canvas);
    // out of sight, it draws nothing (its clock and sound go on)
    const visibility = new IntersectionObserver(([entry]) => {
      if (!entry) return;
      if (this.#player !== p) return;
      p.hide(!entry.isIntersecting);
      this.#after();
    });
    visibility.observe(this);
    signal.addEventListener(
      "abort",
      () => {
        resize.disconnect();
        visibility.disconnect();
      },
      { once: true },
    );
  }

  /** What the player asks (its director to run another scene, full screen), its cursor, and its
   *  next picture, when it is due. */
  #after(): void {
    const p = this.#player;
    if (!p || !this.#connection || this.#connection.signal.aborted) return;
    for (const [ask, value] of p.asks()) {
      if (ask === "scene") {
        this.setAttribute("scene", value);
      } else if (ask === "fullscreen") {
        if (value)
          this.requestFullscreen?.().catch(() => {}); // refused: not full screen
        else if (document.fullscreenElement === this) document.exitFullscreen();
      }
    }
    this.#canvas.style.cursor = p.cursor;
    clearTimeout(this.#timer);
    let wake;
    try {
      wake = p.wake();
    } catch (error) {
      return this.#stop(error);
    }
    if (wake === 0) this.#frame ||= requestAnimationFrame(() => this.#draw());
    else if (wake > 0) this.#timer = setTimeout(() => this.#after(), wake);
  }

  #draw(): void {
    this.#frame = 0;
    try {
      this.#player?.draw();
    } catch (error) {
      return this.#stop(error);
    }
    this.#after();
  }
}

/** Python written indented in HTML, as the file it is. */
function dedent(text: string): string {
  const lines = text.replace(/^\n+|\s+$/g, "").split("\n");
  const indent = Math.min(...lines.filter((l) => l.trim()).map((l) => l.search(/\S/)));
  return lines.map((l) => l.slice(indent)).join("\n") + "\n";
}

/** Define <manimgx-player> (once `settings` are as they should be). Its Python runs in the
 *  worker whose script `worker` gives: the entry point supplies the director it carries. */
export function define(worker: () => string | URL): void {
  script = worker;
  customElements.get("manimgx-player") ?? customElements.define("manimgx-player", ManimgxPlayer);
}

declare global {
  interface HTMLElementTagNameMap {
    "manimgx-player": ManimgxPlayer;
  }
}
