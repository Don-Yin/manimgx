// Compile this like a consumer of the published declarations, without the package's source.
import { ManimgxPlayer, settings, unsupported } from "manimgx";
import type { Failure, SceneError, Unsupported } from "manimgx";

const player: ManimgxPlayer = document.createElement("manimgx-player");
player.source = "class Demo(Scene): pass";
player.source = null;
player.scene = "Demo";
player.scene = null;
player.currentTime = 1.5;
player.play();
player.pause();
const duration: number = player.duration;
const paused: boolean = player.paused;
const source: string | null = player.source;
const scene: string | null = player.scene;
const error: SceneError | null = player.error;
const failure: Failure | null = player.failure;
settings.pyodide = "https://example.test/pyodide/";
settings.manimgx = "https://example.test/manimgx.whl";

// The events: a run's first frame, and a failed run (whose `error` says why).
player.addEventListener("loadeddata", (event: Event) => void event.type);
player.addEventListener("error", (event: ErrorEvent) => {
  const message: string = event.message;
  const line: number = event.lineno;
  const why: SceneError | null = player.error;
  if (why) {
    const { type, trace }: { type: string; trace: string } = why;
    const at: number | null = why.line;
    void [type, trace, at];
  }
  void [message, line];
});

// It cannot play at all: what the browser lacks, found before anything downloads, or what failed.
player.addEventListener("failure", () => {
  const why = player.failure;
  if (why?.reason === "features") {
    const missing: readonly string[] = why.missing;
    void missing;
  } else if (why) {
    const said: string = why.message;
    void said;
  }
});
void unsupported().then((lacking: Unsupported | null) => {
  if (lacking) {
    const reason: "webgpu" | "adapter" | "features" = lacking.reason;
    void reason;
  }
});

// @ts-expect-error Python source must be text.
player.source = 1;
// @ts-expect-error Playback positions use seconds as numbers.
player.currentTime = "1.5";
// @ts-expect-error Duration is reported by the engine and is read-only.
player.duration = 10;
// @ts-expect-error Call play() or pause() to change playback.
player.paused = true;
// @ts-expect-error The player reports why a run failed; it cannot be set.
player.error = null;
// @ts-expect-error A failure's fields are read-only.
error!.message = "";
// @ts-expect-error Why the player cannot play cannot be set.
player.failure = null;
// @ts-expect-error A browser lacks WebGPU, an adapter, or features: Python failing is not one.
const notLacking: Unsupported = { reason: "python", message: "" };
// @ts-expect-error Package requirements and wheel URLs are strings.
settings.manimgx = 1;

void [duration, paused, source, scene, error, failure, notLacking];
