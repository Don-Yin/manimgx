"""Two frames look the same when, blurred by a pixel, they differ by no more than the
tolerance; a film is compared with its reference frame by frame, regardless of how holds are
grouped.

- Light an edge moves into the next pixel cancels out, and a lone pixel fades: how a GPU
  rounds an edge measures well under the tolerance. A stroke moved by a pixel, a dot gone or
  a run of a thin line gone measure beyond it, and a flat change of color measures its size.
- Every frame both films have is compared, and only those that look different are reported,
  with their difference; how many frames each film has is the caller's to compare. Skipped,
  repeated or missing frames fail, and so does a reference video that is not the film its
  facts record.
"""

from collections.abc import Callable
from contextlib import closing
from fractions import Fraction
from itertools import groupby
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from tests.integration.corpus.case import FPS, SIZE, Frames
from tests.integration.corpus.frames import (
    TOLERANCE,
    Comparison,
    Difference,
    Movie,
    Recorder,
    difference,
    frame_hash,
)

type Pair = tuple[np.ndarray, np.ndarray]


def black() -> np.ndarray:
    return np.zeros((40, 60, 3), np.uint8)


def edge() -> np.ndarray:
    """A long vertical edge, its last column a quarter lit, as antialiasing leaves it."""
    frame = black()
    frame[:, :30], frame[:, 30] = 255, 60
    return frame


def rounded_over() -> Pair:
    second = edge()
    second[:, 30], second[:, 31] = 0, 60  # the quarter lands a pixel further
    return edge(), second


def rounded_brighter() -> Pair:
    second = edge()
    second[:, 30] = 100
    return edge(), second


def moved_line() -> Pair:
    first, second = black(), black()
    first[:, 20], second[:, 21] = 255, 255
    return first, second


def gone_dot() -> Pair:
    first = black()
    first[18:21, 28:31] = 255
    return first, black()


def gone_run() -> Pair:
    first = black()
    first[20, :] = 255
    second = first.copy()
    second[20, 20:40] = 0
    return first, second


def lone_pixel() -> Pair:
    second = black()
    second[20, 30] = 60
    return black(), second


def test_identical_frames_do_not_differ() -> None:
    frame = np.random.default_rng(0).integers(0, 256, (40, 60, 3), np.uint8)
    assert difference(frame, frame.copy()) == 0


@pytest.mark.parametrize("shift", [1, 7, 31, -40])
def test_a_flat_change_of_color_measures_its_size(shift: int) -> None:
    frame = np.full((40, 60, 3), 100, np.uint8)
    other = (frame.astype(np.int16) + shift).astype(np.uint8)
    assert difference(frame, other) == pytest.approx(abs(shift))


@pytest.mark.parametrize(
    "pair",
    [rounded_over, rounded_brighter, lone_pixel],
    ids=[
        "an edge's antialiasing a pixel over",
        "an edge rounded brighter",
        "lone pixel",
    ],
)
def test_how_a_gpu_rounds_an_edge_looks_the_same(pair: Callable[[], Pair]) -> None:
    assert difference(*pair()) < TOLERANCE


@pytest.mark.parametrize(
    "pair",
    [moved_line, gone_dot, gone_run],
    ids=["a stroke moved by a pixel", "a dot gone", "a run of a thin line gone"],
)
def test_a_change_a_viewer_sees_looks_different(pair: Callable[[], Pair]) -> None:
    assert difference(*pair()) > TOLERANCE


class Film:
    size = (1, 1)

    def __init__(self, pixels: list[int], *, grouped: bool = True) -> None:
        self.pixels = pixels
        self.frames = len(pixels)
        self.timeline: list[tuple[int, int]] = []
        self.drawn: list[int] = []
        first = 0
        for _, group in groupby(pixels):
            repeat = len(list(group))
            self.timeline.extend(
                [(first, repeat)]
                if grouped
                else [(first + offset, 1) for offset in range(repeat)]
            )
            first += repeat

    def render(self, frame: int) -> bytes:
        self.drawn.append(frame)
        return bytes((self.pixels[frame], 0, 0, 255))


# one pixel's frames: a blur of a constant keeps it, so they differ by their channels'
# difference, within the tolerance (20) or beyond it (40 and up)
levels = st.sampled_from([0, 20, 40, 80])


@given(pairs=st.lists(st.tuples(levels, levels), max_size=50), grouped=st.booleans())
def test_every_frame_is_compared_across_independent_hold_boundaries(
    pairs: list[tuple[int, int]], grouped: bool
) -> None:
    expected = Film([old for old, _ in pairs], grouped=grouped)
    actual = Film([new for _, new in pairs], grouped=not grouped)
    differences: list[Difference] = []
    comparison = Comparison(
        expected, lambda difference, _old, _new: differences.append(difference)
    )
    for index, repeat in actual.timeline:
        comparison.add(index, repeat, bytes((actual.pixels[index], 0, 0)))
    comparison.finish(actual.frames)
    found = {
        frame: d.amount
        for d in differences
        for frame in range(d.first, d.first + d.repeat)
    }
    assert found == pytest.approx(
        {
            index: abs(old - new)
            for index, (old, new) in enumerate(pairs)
            if abs(old - new) > TOLERANCE
        }
    )
    assert expected.drawn == [index for index, _ in expected.timeline]


@pytest.mark.parametrize(("reference", "actual"), [([0, 0], [80] * 3), ([0] * 3, [80])])
def test_only_the_frames_both_films_have_are_compared(
    reference: list[int], actual: list[int]
) -> None:
    differences: list[Difference] = []
    comparison = Comparison(
        Film(reference), lambda difference, _old, _new: differences.append(difference)
    )
    comparison.add(0, len(actual), bytes((actual[0], 0, 0)))
    comparison.finish(len(actual))
    both = min(len(reference), len(actual))
    assert [(d.first, d.repeat) for d in differences] == [(0, both)]
    assert differences[0].amount == pytest.approx(80)


@pytest.mark.parametrize(("index", "repeat"), [(1, 1), (-1, 1), (0, 0), (0, -1)])
def test_gaps_overlaps_and_nonpositive_holds_fail(index: int, repeat: int) -> None:
    comparison = Comparison(Film([0, 0]), lambda *_: None)
    with pytest.raises(ValueError, match="timeline"):
        comparison.add(index, repeat, bytes(3))


def test_a_repeated_callback_cannot_hide_a_missing_frame() -> None:
    comparison = Comparison(Film([0, 0]), lambda *_: None)
    comparison.add(0, 1, bytes(3))
    with pytest.raises(ValueError, match="timeline"):
        comparison.add(0, 1, bytes(3))


@pytest.mark.parametrize("reported", [0, 2, 3])
def test_callbacks_must_cover_the_whole_film(reported: int) -> None:
    comparison = Comparison(Film([0, 0]), lambda *_: None)
    comparison.add(0, 1, bytes(3))
    with pytest.raises(ValueError, match="frame coverage"):
        comparison.finish(reported)


@pytest.mark.parametrize("timeline", [[(1, 2)], [(0, 0)], [(0, 1), (0, 1)], [(0, 1)]])
def test_a_malformed_reference_timeline_is_rejected(
    timeline: list[tuple[int, int]],
) -> None:
    reference = Film([0, 0])
    reference.timeline = timeline
    with pytest.raises(ValueError, match="reference timeline"):
        Comparison(reference, lambda *_: None)


def test_pixel_dimensions_are_checked_before_comparing() -> None:
    comparison = Comparison(Film([0]), lambda *_: None)
    with pytest.raises(ValueError, match="image size"):
        comparison.add(0, 1, bytes(4))


@pytest.mark.parametrize("kept", ["the film", "another frame", "too few frames"])
def test_a_reference_video_is_the_film_its_facts_record(
    kept: str, tmp_path: Path
) -> None:
    width, height = SIZE
    pictures = [bytes([level]) * (width * height * 3) for level in (0, 90)]
    recorded = Recorder(SIZE, FPS, tmp_path / "manimgx.mkv", compact=False)
    for picture in pictures[: 1 if kept == "too few frames" else 2]:
        recorded.add(picture if kept != "another frame" else bytes(len(picture)))
    recorded.close()
    facts = Frames(
        tuple((frame_hash(p), 1) for p in pictures),
        Fraction(2, FPS),
        ((Fraction(0), 2),),
    )
    with closing(Movie(tmp_path / "manimgx.mkv", facts)) as movie:
        assert movie.render(0) == pictures[0]
        if kept == "the film":
            assert movie.render(1) == pictures[1]
            return
        with pytest.raises(ValueError, match="reference video"):
            movie.render(1)
