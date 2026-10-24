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
- Add Manim CE's `partial_bezier_points`, `subdivide_bezier`, `bezier_remap`, `integer_interpolate`, `is_closed` and `get_smooth_cubic_bezier_handle_points` to the package.
- Add `remove_fixed_in_frame_mobjects` to `ThreeDScene` and `Camera`, Manim CE's undo of `add_fixed_in_frame_mobjects`: the camera moves the mobjects again.
- Add `get_height()`, deprecated in favor of `height`, as `get_width()` is in favor of `width`: Manim CE scenes call both.

### Changed

- Render faster: a graph's area reads its points' coordinates all at once, colors mix without numpy's overhead and are converted to OKLab once, and a family is listed in one pass. The frames are the same.
- Draw and encode a film's frames on a thread of their own: the scene's Python no longer waits for the GPU or the encoder, but for the pixels it asks for and its video's end. The videos are the same.
- Hold the API to its declared types, which ty checks where it is called: `add`, `ApplyFunction`, `SurroundingRectangle`, `ArcPolygonFromArcs` and `voices.Fal` no longer check them again as they run, and an `Animation` always has a mobject (`Wait` and a sound pass a plain `Mobject()`, where `None` stood). `interpolate` is typed by what it mixes (numbers, complex numbers or arrays), and `midpoint`, `center_of_mass`, `bezier`, `partial_bezier_points`, `subdivide_bezier` and `bezier_remap` by the array-likes they take (and `subdivide_bezier`'s count by numpy's integers too).
- Show measured render times in a static benchmark chart.
- Use a Markdown table for the benchmark comparison images.
- Install ManimGX in the Quickstart with one command, `pip install manimgx`, and run `manimgx` directly throughout the docs.
- Move the benchmark to `benchmarks/`, whose README explains its scenes, method and results; the README's numbers link to it.
- Arrange the Rendering and sharing page by command, with settings, tall videos and rendering from Python under Render.
- Make `become` give a mobject another's value, member by member: each member takes its counterpart's points, shape and whole style (its joint and cap styles and 3D shading too), and stays itself, updaters and all, where the other has a member drawn as it is in its place; the members it gains come without updaters, and those it has beyond the other's go. What it was never shows through, becoming the same value again changes nothing, the other is left as it was, and a mobject can become itself or one of its own members. A group or a point cloud that becomes a shape holds the shape in a first member. It is faster too.
- End a transform as its target: its mobject becomes the keyframe its last frame shows, so the points and parts its frames gained on the way never outlive it. A morph that follows another starts from the shape the first ended on, not from that shape divided as the first needed it; `Restore` brings back exactly what was saved, and a remover leaves its mobject as it was. Transforms played together on one mobject still compose. Films that chain morphs change slightly.
- Play `TransformFromCopy` forward: the target turns from the mobject's copy into itself as any transform does, its rate function, `path_arc` and `lag_ratio` running from the copy to the target (they ran backward, the arcs bending the other way), and it ends exactly as itself.
- Take NumPy out of the package: a scene imports it itself (`import numpy as np`), and `from manimgx import *` no longer brings `np`.
- Make the voices' names the package's, as every other name is: `m.Fal`, `m.Voice`, `m.Word`, `m.timed`, `m.estimate` and `m.cached`, where they were `m.voices.Fal` and `manimgx.audio.Voice`. `m.voices` is gone.
- Name the settings' module `manimgx.settings`. `manimgx.config` is the settings themselves, as `m.config` is: after `import manimgx.config`, `manimgx.config.Config` failed.

### Fixed

- Number a line's ticks with the decimal places they need: a range on one side of 0 that starts between whole numbers, such as `NumberLine((3.5, 7.5, 1))`, was numbered 4, 4, 6, 6, 8, where its ticks are at 3.5, 4.5, …; a step written with an exponent (`1e-05`) gave no places, and one with round-off (`0.1 + 0.2`) gave 17.
- Give a type checker the package's names: each module lists the names it gives in `__all__`, and each package takes in its children's and gathers their lists, so `m.Scene`, `m.Text`, `m.config` and every other name are the package's, where they were reported as not exported ([#38](https://github.com/academa-labs/manimgx/issues/38)). `from manimgx import *` binds exactly those names, no longer the package's modules too: `manimgx.typing` took the place of the standard library's `typing`.
- Redraw a shape that empties with `always_redraw` without a RecursionError, and keep a mobject's updaters off the member its points move into when a transform aligns it, so a relative updater such as `always_shift` no longer runs twice on them ([#32](https://github.com/academa-labs/manimgx/issues/32)).
- Measure a text's size in `inspect` and `render` at 1080p, which is 1080 px on a video's short side, so a tall video (1080x1920) no longer reports readable text as small ([#37](https://github.com/academa-labs/manimgx/issues/37)).
- Make the folder a video or a storyboard is written in when it is missing (`render -o new/out.mp4`, `inspect -o new/sheet.png` and `Scene.render`), instead of failing with "No such file or directory" ([#34](https://github.com/academa-labs/manimgx/issues/34)).
- Raise a ValueError, naming where it is, for a nested, unclosed or stray bracket in a `say` script, which was spoken and captioned ([#39](https://github.com/academa-labs/manimgx/issues/39)).
- Time and caption speech in the pieces Unicode lets a line break between, so a `say` span in Chinese, Japanese or Thai, written without spaces, is timed by its own characters or words, where the whole sentence was one word ([#40](https://github.com/academa-labs/manimgx/issues/40)). Captions are the text as it is written, at most 42 columns wide (a Chinese or Japanese character takes two); a line never starts with a closing mark such as `，` or `」`, and ends where a sentence does, a quoted one too. A speech's words are found in its text by themselves, so a trimmed speech, or a voice that cuts its words its own way, no longer fails or mistimes a span; and an empty span after the last word starts where that word ends.
- Show an image drawn smaller than its pixels as their mean: each pixel of the video shows the mean of the picture's pixels it covers, however the image is squashed and whatever its `resampling_algorithm`, where it showed the picture at one point, so thin lines broke up and small text was unreadable ([#36](https://github.com/academa-labs/manimgx/issues/36)). An image at its size or larger is drawn as before.
- Keep resources needed by queued video frames until their transparency retries finish, fixing render failures during cache cleanup ([#16](https://github.com/academa-labs/manimgx/issues/16)).
- Draw a storyboard picture without dropping the frame the film holds back, fixing `manimgx render` failures ("unknown shape") under memory pressure.
- Draw a vectorized curve whose function gives a component as one number (`use_vectorized` with `lambda t: (t, t**2, 0)`), which failed with numpy's inhomogeneous-shape error.
- Name a partite layout's vertex that is not in the graph, and a vertex's keywords or an edge's `tip_config` that are not a mapping, in the error raised.
- Preserve the benchmark comparison images' aspect ratios when PyPI narrows the README table.
- Credit Filament, whose code the 3D lighting is adapted from, in the README and the wheels' third-party notices.
- End a `{{…}}` part of a `MathTex` or `Tex` at the `}}` that closes its own braces: `MathTex(r"V={{\tfrac{1}{3}}}B")` split at the fraction's `}}`, so the part was `\tfrac{1}{3` and `get_part_by_tex(r"\tfrac{1}{3}")` found nothing. An escaped brace (`\{` or `\}`) no longer opens or closes a part.

## 0.1.1

### Changed

- Updated package author metadata to Academa Team. The font packages have metadata-only post-releases; their font files are unchanged.

### Fixed

- Fixed GPU validation failures when meshes with materials share a scene with ordinary meshes, overlays, or point sprites, including during fades.

## 0.1.0

First release of ManimGX.
