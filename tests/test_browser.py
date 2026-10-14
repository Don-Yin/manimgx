"""The browser worker's Python source lifetime, exercised by the real Python interpreter."""

import linecache
import os
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest


class Channel:
    """What the worker gives a run, as it gives it to Pyodide: the take's bytes, that the run
    has made its first frame, and why it failed."""

    def __init__(self) -> None:
        self.told: list[str] = []  # which of the three it told, in order
        self.out: list[bytes] = []  # the take's bytes
        self.failures: list[tuple[str, str, str, int | None]] = []  # why, as told

    def feed(self, data: bytes) -> None:
        self.told.append("feed")
        self.out.append(data)

    def frame(self) -> None:
        self.told.append("frame")

    def fail(self, message: str, kind: str, trace: str, line: int | None) -> None:
        self.told.append("fail")
        self.failures.append((message, kind, trace, line))


Run = Callable[[int, str, str | None, Channel, list[str]], str | None]
Drop = Callable[[int], None]


@pytest.fixture
def runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[Run, Drop]]:
    ffi = ModuleType("pyodide.ffi")
    ffi.__dict__["to_js"] = lambda data: data
    monkeypatch.setitem(sys.modules, "pyodide.ffi", ffi)
    # This is the actual Python program shipped inside the browser worker. Only Pyodide's
    # byte transport and its virtual filesystem root differ from the native interpreter.
    source = (
        Path("browser/src/director.ts")
        .read_text(encoding="utf-8")
        .split("const RUNNER = `\n", 1)[1]
    )
    module = ModuleType("browser_runner")
    exec(source.split("\n`;", 1)[0], module.__dict__)
    module.__dict__["FILMS"] = tmp_path
    run = cast(Run, module.__dict__["run"])
    drop = cast(Drop, module.__dict__["drop"])
    previous = sys.modules.get("scene")
    try:
        yield run, drop
    finally:
        for directory in tmp_path.iterdir():
            if directory.is_dir():
                drop(int(directory.name))
        if previous is not None:
            sys.modules["scene"] = previous


SCENE = """
from pathlib import Path
from manimgx import Scene

class Film(Scene):
    def render(self, *, take):
        path = Path(__file__).with_name("cache.txt")
        with path.open("a", encoding="utf-8") as stream:
            stream.write("one")
        take(b"one")
"""


def test_film_drop_owns_its_source_cache_and_module(
    runner: tuple[Run, Drop], tmp_path: Path
) -> None:
    run, drop = runner
    channel = Channel()
    assert run(1, SCENE, None, channel, []) is None
    assert channel.out[-1] == b"one"
    first = tmp_path / "1" / "scene.py"
    assert linecache.getline(str(first), 2) == "from pathlib import Path\n"
    assert run(2, SCENE, None, channel, []) is None
    second = sys.modules["scene"]
    drop(1)
    drop(1)  # a repeated detach does not own any new work
    assert not first.parent.exists()
    assert str(first) not in linecache.cache
    assert sys.modules["scene"] is second
    assert (tmp_path / "2" / "cache.txt").read_text(encoding="utf-8") == "one"
    drop(2)
    assert not (tmp_path / "2").exists()
    assert "scene" not in sys.modules


def test_same_film_edits_preserve_files_and_execute_the_supplied_source(
    runner: tuple[Run, Drop], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, _ = runner
    write_text = Path.write_text

    def write(path: Path, source: str, *, encoding: str) -> int:
        size = write_text(path, source, encoding=encoding)
        # Browser edits routinely have the same length and land within one filesystem clock
        # tick. Python's timestamp bytecode cache must not substitute the previous source.
        os.utime(path, (1_700_000_000, 1_700_000_000))
        return size

    monkeypatch.setattr(Path, "write_text", write)
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    channel = Channel()
    run(1, SCENE, None, channel, [])
    assert channel.out[-1] == b"one"
    run(1, SCENE.replace("one", "two"), None, channel, [])
    assert channel.out[-1] == b"two"
    assert (tmp_path / "1" / "cache.txt").read_text(encoding="utf-8") == "onetwo"


def test_failed_and_retrying_films_release_their_source_on_drop(
    runner: tuple[Run, Drop], tmp_path: Path
) -> None:
    run, drop = runner
    channel = Channel()
    assert run(1, "raise ValueError('bad scene')", None, channel, []) is None
    assert channel.told == ["fail"]
    assert run(2, "import nonexistent_browser_scene_dependency", None, channel, []) == (
        "nonexistent_browser_scene_dependency"
    )
    for film in [1, 2]:
        assert (tmp_path / str(film) / "scene.py").is_file()
        drop(film)
        assert not (tmp_path / str(film)).exists()


# Scenes that really make a take, to see what a run tells its page of it.
MOVING = """
import manimgx as m

class Moving(m.Scene):
    def construct(self):
        circle = m.Circle()
        self.add(circle)
        self.play(circle.animate.shift(m.RIGHT), run_time=0.5)
        self.wait(0.2)
"""

FAILS_FIRST = """
import manimgx as m

class Fails(m.Scene):
    def construct(self):
        self.play(m.Create(missing_name))
"""

FAILS_LATER = """
import manimgx as m

class Fails(m.Scene):
    def construct(self):
        circle = m.Circle()
        self.play(m.Create(circle), run_time=0.3)
        missing_name
"""


def test_a_run_tells_when_it_has_made_its_first_frame_once(
    runner: tuple[Run, Drop],
) -> None:
    run, _ = runner
    channel = Channel()
    assert run(1, MOVING, None, channel, []) is None
    told = channel.told
    # after the scenes note and the take's first bytes, once, and then the take goes on
    assert told[:3] == ["feed", "feed", "frame"]
    assert told.count("frame") == 1
    assert told.count("fail") == 0
    assert told[-1] == "feed"


def test_a_run_that_fails_before_any_frame_tells_why_and_no_frame(
    runner: tuple[Run, Drop], tmp_path: Path
) -> None:
    run, _ = runner
    channel = Channel()
    assert run(1, FAILS_FIRST, None, channel, []) is None
    # the scenes note, the take's start and end (a failed one), then the error
    assert channel.told == ["feed", "feed", "fail"]
    [(message, kind, trace, line)] = channel.failures
    assert (message, kind, line) == (
        "name 'missing_name' is not defined",
        "NameError",
        6,
    )
    path = tmp_path / "1" / "scene.py"
    # the scene's own frames, as the player shows them, then the error
    assert trace.startswith(
        f'  File "{path}", line 6, in construct\n    self.play(m.Create(missing_name))\n'
    )
    assert "NameError: name 'missing_name' is not defined" in trace


def test_a_run_that_fails_after_its_first_frame_tells_the_frame_then_why(
    runner: tuple[Run, Drop],
) -> None:
    run, _ = runner
    channel = Channel()
    assert run(1, FAILS_LATER, None, channel, []) is None
    told = channel.told
    assert told.count("frame") == 1
    assert told.index("frame") < told.index("fail") == len(told) - 1
    [(message, kind, _, line)] = channel.failures
    assert (message, kind, line) == (
        "name 'missing_name' is not defined",
        "NameError",
        8,
    )


@pytest.mark.parametrize(
    ("source", "kind", "line"),
    [
        (
            "def construct(:\n",
            "SyntaxError",
            1,
        ),  # in no frame of the scene's: its own line
        ("import manimgx as m\nraise ValueError('bad')\n", "ValueError", 2),
        (
            "import manimgx as m\nx = m.Scene\n",
            "ValueError",
            None,
        ),  # it defines no scene
    ],
)
def test_a_run_tells_the_line_it_failed_at_if_it_has_one(
    runner: tuple[Run, Drop], source: str, kind: str, line: int | None
) -> None:
    run, _ = runner
    channel = Channel()
    assert run(1, source, None, channel, []) is None
    assert channel.told == ["fail"]
    [(_, error, _, at)] = channel.failures
    assert (error, at) == (kind, line)
