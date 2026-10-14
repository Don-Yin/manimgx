# ManimGX

[ManimGX](https://manimgx.academa.ai/) in the browser: a scene written in Python, with Manim
Community Edition's API, made and played in the page by ManimGX's own player, drawn with
WebGPU.

```sh
npm install manimgx
```

```html
<script type="module">
  import "manimgx";
</script>

<manimgx-player autoplay>
  <script type="text/python">
    import manimgx as m

    class Euler(m.Scene):
        def construct(self):
            circle = m.Circle(color=m.BLUE, fill_opacity=0.5)
            self.play(m.Create(circle), m.Write(m.MathTex(r"e^{i\pi} + 1 = 0").next_to(circle, m.DOWN)))
  </script>
</manimgx-player>
```

Or from JavaScript:

```js
import "manimgx";

const player = document.createElement("manimgx-player");
player.source = code; // a Python module; set it again, and the film is made again, the time kept
document.body.append(player);
```

- **Python, in the page.** [Pyodide](https://pyodide.org) runs the scene in a Web Worker, with
  ManimGX installed from PyPI (the same version as this package). Nothing runs on a server.
- **ManimGX's own player**, the one `manimgx preview` plays a file in: the engine compiled to
  WebAssembly draws the film with WebGPU, and its face over it: the controls, the time, the
  timeline in the scene's plays (each named by its line of code), captions, the scene's error
  and the keys (`?` lists them), all in ManimGX's fonts. A click, a tap and a key do the same.
- **Any frame, at once**: the film is recorded as it is made (a _take_: each shape once, then
  each frame), and any moment of it is drawn at once, so it plays before the scene has
  finished and seeks instantly. Each frame is drawn at the size the page shows it, in the
  screen's own pixels: sharp at any size, full screen too.
- **For scripts**: `play()`, `pause()`, `paused`, `currentTime`, `duration`, and `scene`; and,
  as a media element tells its page how it fares, the `loadeddata`, `error` and `failure`
  events and the `error` and `failure` properties (see [Events](#events)).

The first film downloads Python (Pyodide, about 6 MB) and ManimGX (about 20 MB); the browser
keeps both. It needs WebGPU, with a GPU that blends float32 targets (`float32-blendable`) and
has float32 depth with stencil (`depth32float-stencil8`): a view adds its coverage in a float32
target, and the renderer's reversed-Z depth needs floating-point precision. Chrome and Edge
have both on Windows, macOS and ChromeOS, and on many Android phones; Safari has them from
version 26, on macOS 26 and iOS 26; Firefox does not blend float32 targets before version 158.
A player checks the browser before it downloads anything, and `unsupported()` tells a page the
same before it makes one (see [When it cannot play](#when-it-cannot-play)).

One file, no dependencies, any bundler. On the command line, `manimgx preview scene.py` plays a
scene file in a window of its own: the same player.

## Events

A page learns how the scene fares as it does from a media element:

```js
player.addEventListener("loadeddata", () => {
  // a run of the scene has made its first frame; player.error is null
});
player.addEventListener("error", () => {
  const { message, type, line, trace } = player.error;
  console.error(`${type} at line ${line}: ${message}`);
});
```

- **`loadeddata`** fires for each run of the scene, when the run has made its first frame. A run
  that fails before it makes one fires no `loadeddata`.
- **`error`** fires, as an `ErrorEvent`, for each run that fails: with an error the scene raised,
  or with a package it imports that would not install. The player also shows the error over the
  last picture it has.
- **`player.error`** is why the latest run failed, until a later run makes its first frame, and
  null before: `{ message, type, line, trace }`. These are Python's message and error class, the
  line of the source the error is at (`null` if none is known), and the lines of the scene's code
  it went through, then the error. It cannot be set. It is set when `error` fires, and cleared
  when `loadeddata` does.

## When it cannot play

A run's error leaves the player playing: the next run may succeed. A player that cannot play at
all says why in the player, and tells the page:

```js
import { unsupported } from "manimgx";

const lacking = await unsupported(); // before making a player: null if this browser can play
player.addEventListener("failure", () => {
  const { reason, message } = player.failure;
});
```

- **`unsupported()`** finds out what this browser lacks to play films, without downloading
  anything, once for the page: `{ reason: "webgpu" }` (no WebGPU), `{ reason: "adapter" }`
  (WebGPU found no GPU to draw with), or `{ reason: "features", missing }` (the GPU lacks what
  the engine draws with, in WebGPU's names). It is null if the browser lacks nothing.
- **`failure`** fires once, when the player cannot play: for what the browser lacks, found
  before Python downloads, or later, `{ reason: "python" }` (Python or ManimGX would not
  download or start) or `{ reason: "engine" }` (the engine failed).
- **`player.failure`** is why, with a `message` that says it as the player shows it; null
  before. A failed player stays failed. A player made later begins again, so a page can try
  again by making another.
