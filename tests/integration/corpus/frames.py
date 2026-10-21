"""Frames: their identity (a hash of their pixels), their storage (lossless video), and when
two look the same.

A frame is identified by its RGB pixels alone, never by the bytes of a file, so a video is
rewritten only when its pixels change: re-rendering an unchanged scene changes no file.
Videos are x264 in RGB at QP 0 — lossless, and byte-reproducible for a given encoder (one
thread, bit-exact muxing) — written and read with PyAV (FFmpeg's libraries, in its wheel).

Two frames look the same when they differ by no more than `TOLERANCE` once both are blurred
by a pixel (`difference`), as an eye blurs them: an edge that one GPU rounds into the next
pixel cancels out, while a stroke moved or a mark gone does not. A film is compared with its
reference frame by frame as it is drawn (`Comparison`), the reference read from its video
(`Movie`).
"""

import hashlib
from collections.abc import Callable, Generator
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Protocol

import av
import numpy as np
from tests.integration.corpus.case import SIZE, Frames, Run

type Pixels = np.ndarray[tuple[int, int, int], np.dtype[np.uint8]]
"""One frame: height × width × RGB."""


TOLERANCE = 30
"""How much two frames may differ (`difference`, out of 255) and look the same. Machines
round an edge differently by up to 28 (an Apple GPU, a virtual machine's and a CPU
rasterizer, over the whole corpus, a chaotic scene aside); a stroke moved by a pixel, or a
dot or a run of a thin line gone, differ by 40 and more."""

_RADIUS = 4
_BLUR = np.exp(-0.5 * np.arange(-_RADIUS, _RADIUS + 1) ** 2)
_BLUR /= _BLUR.sum()  # a Gaussian of a pixel's sigma, cut off at four


def difference(a: Pixels, b: Pixels) -> float:
    """How differently two frames look: the largest difference of a channel anywhere, once
    both are blurred by a Gaussian of a pixel's sigma. Light that an edge moves into the next
    pixel cancels out, so how a GPU rounds an edge hardly counts."""
    d = b.astype(np.float64) - a
    ys, xs = np.nonzero(d.any(axis=2))
    if not len(ys):
        return 0.0
    # all the blur reaches: what changed and a radius around it, reflected at the frame's edges
    height, width = d.shape[:2]
    top, bottom = max(ys.min() - _RADIUS, 0), min(ys.max() + _RADIUS + 1, height)
    left, right = max(xs.min() - _RADIUS, 0), min(xs.max() + _RADIUS + 1, width)
    margin = (_RADIUS, _RADIUS)
    window = np.pad(
        d[top:bottom, left:right], (margin, margin, (0, 0)), mode="symmetric"
    )
    view = np.lib.stride_tricks.sliding_window_view
    rows = view(window, _BLUR.size, axis=0) @ _BLUR
    blurred = view(rows, _BLUR.size, axis=1) @ _BLUR
    return float(np.abs(blurred).max())


def frame_hash(rgb: bytes) -> str:
    return hashlib.sha256(rgb).hexdigest()[:16]


def rgb(pixels: bytes | np.ndarray, size: tuple[int, int]) -> bytes:
    """RGB bytes of a frame given as RGBA (or RGB) rows, top to bottom."""
    width, height = size
    array = np.frombuffer(pixels, np.uint8) if isinstance(pixels, bytes) else pixels
    channels = array.size // (width * height)
    frame = array.reshape(height, width, channels)
    return np.ascontiguousarray(frame[:, :, :3]).tobytes()


class Recorder:
    """Frames as an engine draws them: their hashes, as runs, and, given a path, a video."""

    def __init__(
        self,
        size: tuple[int, int],
        fps: int,
        video: Path | None,
        *,
        compact: bool = True,
    ) -> None:
        self.size = size
        self.runs: list[list[str | int]] = []
        self.count = 0
        self._video = None if video is None else _Video(video, size, fps, compact)

    def add(self, frame: bytes, repeat: int = 1) -> None:
        """One drawn frame (RGB bytes), shown `repeat` times."""
        if repeat <= 0:
            return
        h = frame_hash(frame)
        if self.runs and self.runs[-1][0] == h:
            self.runs[-1][1] = int(self.runs[-1][1]) + repeat
        else:
            self.runs.append([h, repeat])
        self.count += repeat
        if self._video is not None:
            self._video.write(frame, repeat)

    def close(self) -> tuple[Run, ...]:
        if self._video is not None:
            self._video.close()
        return tuple((str(h), int(n)) for h, n in self.runs)


class _Video:
    """Lossless RGB video, compressed for archiving or for immediate comparison."""

    def __init__(
        self, path: Path, size: tuple[int, int], fps: int, compact: bool
    ) -> None:
        self.size, self.rate, self.shown = size, Fraction(1, fps), 0
        self.container = av.open(str(path), "w", options={"fflags": "+bitexact"})
        options = {
            "preset": "veryslow" if compact else "ultrafast",
            "qp": "0",
            "threads": "1",
            "flags": "+bitexact",
        }
        self.stream = self.container.add_stream("libx264rgb", fps, options=options)
        self.stream.width, self.stream.height = size
        self.stream.pix_fmt = "rgb24"

    def write(self, frame: bytes, repeat: int) -> None:
        width, height = self.size
        pixels = np.frombuffer(frame, np.uint8).reshape(height, width, 3)
        picture = av.VideoFrame.from_ndarray(pixels, format="rgb24")
        picture.time_base = self.rate
        for _ in range(repeat):
            picture.pts = self.shown
            self.shown += 1
            self.container.mux(self.stream.encode(picture))

    def close(self) -> None:
        self.container.mux(self.stream.encode(None))
        self.container.close()


def decode(path: Path, size: tuple[int, int]) -> Generator[Pixels]:
    """Every frame of a video, in order. A reader may stop early; a video that fails to decode
    to its end raises."""
    width, height = size
    with av.open(str(path)) as container:
        for frame in container.decode(video=0):
            if (frame.width, frame.height) != size:
                msg = f"{path}: a frame of {frame.width}x{frame.height}"
                raise RuntimeError(msg)
            pixels = frame.to_ndarray(format="rgb24").astype(np.uint8, copy=False)
            yield pixels.reshape(height, width, 3)


@dataclass(frozen=True, slots=True)
class Difference:
    """Frames that look different from their reference's: `repeat` frames from `first`,
    which differ by as much as `amount` (`difference`)."""

    first: int
    repeat: int
    amount: float


class RecordedFilm(Protocol):
    size: tuple[int, int]
    frames: int
    timeline: list[tuple[int, int]]

    def render(self, frame: int) -> bytes: ...


class Comparison:
    """A film's frames against its reference's as they are drawn, however either groups its
    holds: those that look different, as runs, each handed over with both pictures while
    they are at hand. The frames both films have are compared; how many each has is for the
    caller to compare. Indexes and holds must partition the film: skipped, repeated and
    missing frames fail."""

    def __init__(
        self,
        reference: RecordedFilm,
        differs: Callable[[Difference, bytes, bytes], object],
    ) -> None:
        end = 0
        for start, repeat in reference.timeline:
            if start != end or repeat <= 0:
                raise ValueError("the reference timeline must cover consecutive frames")
            end += repeat
        if end != reference.frames or min(reference.size) <= 0:
            raise ValueError("the reference timeline or image size is inconsistent")
        self.reference, self.differs = reference, differs
        self.frames = 0
        self._shot = 0
        self._wanted: bytes | None = None

    def add(self, index: int, repeat: int, actual: bytes) -> None:
        """Compare RGB pixels shown at `index` for `repeat` frames."""
        if index != self.frames or repeat <= 0:
            raise ValueError("the actual timeline must cover consecutive frames")
        width, height = self.reference.size
        if len(actual) != width * height * 3:
            raise ValueError("the actual frame has the wrong RGB image size")
        end = index + repeat
        while self.frames < min(end, self.reference.frames):
            start, held = self.reference.timeline[self._shot]
            if self._wanted is None:
                self._wanted = rgb(self.reference.render(start), self.reference.size)
            stop = min(end, start + held)
            if actual != self._wanted:
                old, new = (
                    np.frombuffer(pixels, np.uint8).reshape(height, width, 3)
                    for pixels in (self._wanted, actual)
                )
                amount = difference(old, new)
                if amount > TOLERANCE:
                    found = Difference(self.frames, stop - self.frames, amount)
                    self.differs(found, self._wanted, actual)
            self.frames = stop
            if stop == start + held:
                self._shot += 1
                self._wanted = None
        self.frames = end

    def finish(self, frames: int) -> None:
        """Require the frames compared, or passed, to be the film's, every one."""
        if frames != self.frames:
            raise ValueError(
                f"frame coverage differs: callbacks={self.frames}, film={frames}"
            )


class Movie:
    """A reference film read from its video, a frame after another, each checked against the
    hash its facts record: the video is the reference only as the film its facts describe."""

    def __init__(self, path: Path, facts: Frames) -> None:
        self.size, self.frames = SIZE, facts.count
        self.timeline = [(i, 1) for i in range(self.frames)]
        self._hashes = facts.hashes()
        self._decoded = decode(path, SIZE)

    def render(self, frame: int) -> bytes:
        pixels = next(self._decoded, None)
        if pixels is None:
            raise ValueError("the reference video ends before its recorded frames")
        drawn = pixels.tobytes()
        if frame_hash(drawn) != self._hashes[frame]:
            msg = f"the reference video's frame {frame} is not the one its facts record"
            raise ValueError(msg)
        return drawn

    def close(self) -> None:
        self._decoded.close()
