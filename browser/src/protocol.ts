/** Messages shared by the page and its Python worker. */
export interface Boot {
  pyodide: string;
  manimgx: string;
}

export interface Run {
  source: string;
  scene: string | null;
}

export type ToDirector = { boot: Boot } | { film: number; run: Run } | { film: number; drop: true };

/** These byte arrays originate in Pyodide and own transferable ArrayBuffers. */
export interface EngineFiles {
  js: string;
  wasm: Uint8Array<ArrayBuffer>;
  fonts: Uint8Array<ArrayBuffer>[];
}

/** Why a run of the scene failed: the error the scene raised, as the player shows it over the
 *  last picture the scene made. */
export interface SceneError {
  /** What the error says (Python's `str(error)`). */
  readonly message: string;
  /** The error's class, as Python names it: `"NameError"`, `"SyntaxError"`. */
  readonly type: string;
  /** The line of the scene's source it failed at (the first is 1), if it is known. */
  readonly line: number | null;
  /** What the player shows: the lines of the scene's code the error went through, then the
   *  error. For a failure that is not the scene's own (a package that would not install), its
   *  message. */
  readonly trace: string;
}

/** What a browser lacks to play films, found before anything downloads: WebGPU itself
 *  (`webgpu`), a GPU that WebGPU can draw with (`adapter`), or what the engine needs of that GPU
 *  (`features`: those it lacks, in WebGPU's names). `message` says it as the player shows it. */
export type Unsupported =
  | { readonly reason: "webgpu"; readonly message: string }
  | { readonly reason: "adapter"; readonly message: string }
  | { readonly reason: "features"; readonly message: string; readonly missing: readonly string[] };

/** Why a player cannot play at all, unlike a run's error, after which the next run may play: what
 *  its browser lacks, or what failed later, Python or ManimGX not downloading or starting
 *  (`python`) or the engine (`engine`). `message` says it as the player shows it. */
export type Failure =
  | Unsupported
  | { readonly reason: "python"; readonly message: string }
  | { readonly reason: "engine"; readonly message: string };

/** What the worker says. A film's messages are its take stream (`feed`), once its run has made
 *  its first frame (`frame`), and why a run failed (`error`: the scene's, not the runtime's,
 *  which is `failure`). */
export type FromDirector =
  | { status: string }
  | { failure: string }
  | { engine: EngineFiles }
  | { film: number; feed: ArrayBuffer }
  | { film: number; frame: true }
  | { film: number; error: SceneError };

export function message(error: unknown): string {
  return String(
    typeof error === "object" && error !== null && "message" in error
      ? (error.message ?? error)
      : error,
  );
}
