// The director's worker: Python (Pyodide) running scenes, their takes sent to the page's players.
// ManimGX comes from PyPI (micropip), and with it the player's engine, which is handed on.
//
// In: {boot: {pyodide, ManimGX}} once; {film, run: {source, scene}}; {film, drop} on detach.
// Out: {status} while it boots (what it waits for); {engine: {js, wasm, fonts}} once (the
// player: its JS and WebAssembly, and the fonts its face is set in); then each film's take stream,
// {film, feed}: its takes, and between them the director's notes (the file's scenes, an error),
// which the player reads like every other note. Beside the stream, for the page's element:
// {film, frame} when a run has made its first frame, {film, error} when a run failed (the same
// error as the note the player shows).

import { message } from "./protocol.js";
import type { Boot, FromDirector, Run, SceneError, ToDirector } from "./protocol.js";

interface PythonValue {
  toJs(): unknown;
  destroy(): void;
}

interface Micropip {
  install(requirement: string): Promise<void>;
}

interface Pyodide {
  loadPackage(name: string): Promise<void>;
  loadPackagesFromImports(source: string): Promise<void>;
  pyimport(name: string): unknown;
  runPython(source: string): unknown;
}

interface PyodideModule {
  loadPyodide(options: { indexURL: string }): Promise<Pyodide>;
}

/** What a film's run tells its page, and Python calls: the take's bytes, that the run has made
 *  its first frame, and why it failed (`line`: none if Python knows of none). */
interface Channel {
  feed(bytes: Uint8Array<ArrayBuffer>): void;
  frame(): void;
  fail(message: string, type: string, trace: string, line: number | undefined): void;
}

type Runner = (
  film: number,
  source: string,
  scene: string | null,
  channel: Channel,
  tried: string[],
) => string | null;

interface Python {
  py: Pyodide;
  micropip: Micropip;
  runner: Runner;
  note: (text: string) => Uint8Array<ArrayBuffer>;
  drop: (film: number) => void;
}

const queue = new Map<number, Run | null>(); // the latest run, or teardown after the active run
let booted: Promise<Python | null> | undefined;
let busy = false;
let failed = false;

function send(data: FromDirector, transfer: Transferable[] = []): void {
  postMessage(data, transfer);
}

onmessage = ({ data }: MessageEvent<ToDirector>) => {
  if ("boot" in data) {
    booted = boot(data.boot).catch((error: unknown) => {
      failed = true;
      queue.clear();
      send({ failure: `ManimGX could not start: ${message(error)}` });
      return null;
    });
    return;
  }
  if (!failed) {
    queue.set(data.film, "run" in data ? data.run : null);
    drain();
  }
};

async function boot({ pyodide, manimgx }: Boot): Promise<Python> {
  send({ status: "Loading Python…" });
  const { loadPyodide } = (await import(`${pyodide}pyodide.mjs`)) as PyodideModule;
  const py = await loadPyodide({ indexURL: pyodide });
  send({ status: "Installing ManimGX…" });
  await py.loadPackage("micropip");
  const micropip = py.pyimport("micropip") as Micropip;
  await micropip.install(manimgx);
  // the player's engine, in the engine the wheel holds, beside the Python it plays for
  const built = py.runPython(`
from manimgx import _engine
from manimgx.drawing.typesetting import FONTS
(*_engine.web(), _engine.face_fonts(list(FONTS)))`) as PythonValue;
  const [js, wasm, fonts] = built.toJs() as [
    string,
    Uint8Array<ArrayBuffer>,
    Uint8Array<ArrayBuffer>[],
  ];
  built.destroy();
  send({ engine: { js, wasm, fonts } }, [wasm.buffer, ...fonts.map((f) => f.buffer)]);
  const runner = py.runPython(RUNNER) as Runner;
  const note = py.runPython("lambda text: to_js(_engine.note(text))") as Python["note"];
  const drop = py.runPython("drop") as Python["drop"];
  return { py, micropip, runner, note, drop };
}

async function drain(): Promise<void> {
  const python = await booted;
  if (!python || busy) return;
  const { py, micropip, runner, note, drop } = python;
  busy = true;
  try {
    for (const [film, run] of queue) {
      queue.delete(film);
      const feed = (bytes: Uint8Array<ArrayBuffer>): void =>
        send({ film, feed: bytes.buffer }, [bytes.buffer]);
      // A failure goes to the player in the film's note stream, shown over the last picture,
      // and to the page's element as it is.
      const fail = (error: SceneError): void => {
        feed(note(JSON.stringify({ error })));
        send({ film, error });
      };
      const channel: Channel = {
        feed,
        frame: () => send({ film, frame: true }),
        fail: (text, type, trace, line) => fail({ message: text, type, line: line ?? null, trace }),
      };
      try {
        if (run === null) {
          drop(film);
          continue;
        }
        const { source, scene } = run;
        await py.loadPackagesFromImports(source); // the scene's Pyodide package imports
        // A missing module is installed once, then the ordinary runner reports any failure.
        const tried: string[] = [];
        for (let missing; (missing = runner(film, source, scene ?? null, channel, tried));) {
          tried.push(missing);
          await micropip.install(missing).catch(() => {});
        }
      } catch (error) {
        // Loading and calling Python can fail outside its own scene error boundary. Report it
        // as this film's error so another film or edit can still run.
        const text = message(error);
        fail({ message: text, type: "Error", line: null, trace: text });
      }
      await new Promise<void>((resolve) => setTimeout(resolve)); // let newer runs in
    }
  } finally {
    busy = false;
    if (queue.size) drain();
  }
}

// Python: a film's source run as a scene file, like `manimgx render` runs one, its take sent on.
const RUNNER = `
import dataclasses, importlib.util, json, linecache, shutil, sys, traceback
from pathlib import Path
from pyodide.ffi import to_js
from manimgx import _engine
from manimgx.config import Config, config
from manimgx.scene import Scene

FILMS = Path("/home/pyodide/films")

def run(film, source, name, channel, tried):
    out = lambda data: channel.feed(to_js(data))
    path = FILMS / str(film) / "scene.py"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        linecache.cache.pop(str(path), None)
        defaults = Config()
        for field in dataclasses.fields(Config):
            setattr(config, field.name, getattr(defaults, field.name))
        spec = importlib.util.spec_from_file_location("scene", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["scene"] = module
        exec(compile(source, str(path), "exec"), module.__dict__)
        scenes = [v for v in vars(module).values() if isinstance(v, type) and issubclass(v, Scene) and v.__module__ == "scene"]
        names = [s.__name__ for s in scenes]
        if not scenes:
            raise ValueError("the source defines no scene (a subclass of manimgx.Scene)")
        kind = scenes[names.index(name)] if name in names else scenes[0]
        out(_engine.note(json.dumps({"scenes": names, "scene": kind.__name__})))
        scene = kind()
        framed = False

        def take(data):
            nonlocal framed
            out(data)
            if not framed and scene.film.frame_count:
                framed = True
                channel.frame()  # the film has its first frame

        scene.render(take=take)
    except ModuleNotFoundError as error:
        if error.name and error.name not in list(tried):
            return error.name  # installed, then run again
        report(channel, path, error)
    except Exception as error:
        report(channel, path, error)

def drop(film):
    path = FILMS / str(film) / "scene.py"
    module = sys.modules.get("scene")
    if getattr(module, "__file__", None) == str(path):
        del sys.modules["scene"]
    for filename in list(linecache.cache):
        if Path(filename).is_relative_to(path.parent):
            del linecache.cache[filename]
    if path.parent.exists():
        shutil.rmtree(path.parent)

def report(channel, path, error):
    # the scene's own frames, not manimgx's or Pyodide's
    frames = [f for f in traceback.extract_tb(error.__traceback__) if f.filename == str(path)]
    trace = "".join(traceback.format_list(frames) + traceback.format_exception_only(error))
    line = frames[-1].lineno if frames else getattr(error, "lineno", None)
    channel.fail(str(error), type(error).__name__, trace, line)

run
`;
