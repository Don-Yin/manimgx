---
hide:
  - navigation
---

# Changelog

The notable changes to ManimGX, release by release. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and ManimGX follows
[Semantic Versioning](https://semver.org/).

<!--
### Added
### Changed
### Fixed
### Removed
-->

## Unreleased

### Added

- Add a preview image and social metadata when sharing website and documentation links.
- Credit Academa and the creators in the README.
- Tell a page how a scene fares in `<manimgx-player>`, as a media element does: a `loadeddata` event when a run of the scene has made its first frame, and an `error` event when a run fails, with the error's `message`, `type`, `line` and `trace` in `player.error` until a later run makes its first frame.
- Tell a page when `<manimgx-player>` cannot play at all: a `failure` event, with why in `player.failure` (the browser has no WebGPU, no GPU WebGPU can draw with, or a GPU without float32 blending or float32 depth with stencil; or Python, ManimGX or the engine failed). `unsupported()` finds out what the browser lacks before a page makes a player.

### Changed

- Show measured render times in a static benchmark chart.
- Use a Markdown table for the benchmark comparison images.
- Install ManimGX in the Quickstart with one command, `pip install manimgx`, and run `manimgx` directly throughout the docs.
- Move the benchmark to `benchmarks/`, whose README explains its scenes, method and results; the README's numbers link to it.
- Arrange the Rendering and sharing page by command, with settings, tall videos and rendering from Python under Render.
- Check the browser's GPU before downloading Python: a browser that cannot draw a film no longer downloads Pyodide and ManimGX to find out. A player made after one failed begins again, so a page can retry a download that failed.

### Fixed

- Keep resources needed by queued video frames until their transparency retries finish, fixing render failures during cache cleanup ([#16](https://github.com/academa-labs/manimgx/issues/16)).
- Preserve the benchmark comparison images' aspect ratios when PyPI narrows the README table.
- Credit Filament, whose code the 3D lighting is adapted from, in the README and the wheels' third-party notices.
- Keep webpack from compiling the player's import of its engine into "Cannot find module": the bundle tells bundlers to leave that import alone.

## 0.1.1

### Changed

- Updated package author metadata to Academa Team. The font packages have metadata-only post-releases; their font files are unchanged.

### Fixed

- Fixed GPU validation failures when meshes with materials share a scene with ordinary meshes, overlays, or point sprites, including during fades.

## 0.1.0

First release of ManimGX.
