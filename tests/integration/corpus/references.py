"""Making a case's references: render each engine, keep a video only when its pixels change,
compare the two, and record the facts. ManimGX's reference stays while its frames look the
same (`frames.TOLERANCE`) and keep their times: it changes only when they don't. Nothing in
a case changes until its new facts are whole."""

import hashlib
import importlib.metadata
import importlib.util
import shutil
import tempfile
from contextlib import closing
from pathlib import Path

from tests.integration.corpus import compare as comparing
from tests.integration.corpus import engines
from tests.integration.corpus.case import (
    ENGINES,
    FPS,
    SIZE,
    Case,
    Comparison,
    Engine,
    Facts,
    Failure,
    Frames,
)
from tests.integration.corpus.frames import Comparison as FrameComparison
from tests.integration.corpus.frames import Difference, Movie, decode


def render(case: Case, wanted: set[Engine]) -> tuple[Facts, str]:
    """Render `case` with the wanted engines (both when its source changed), compare, and
    record the facts; them, and what changed."""
    old = case.facts()
    source = case.source_hash()
    current = case.current(old)
    if not current:
        wanted = set(ENGINES)
    renders_ce = "ce" in wanted or old is None or old.render("ce") is None
    if renders_ce and importlib.util.find_spec("manim") is None:
        msg = f"{case.name}: CE's references need Manim CE (`uv sync --group ce`)"
        raise RuntimeError(msg)
    renders: dict[Engine, Frames | Failure] = {}
    # each engine's video as the new facts see it, and what a render puts in its place (or
    # takes out of it) once they are whole
    videos = {engine: case.video(engine) for engine in ENGINES}
    placed: dict[Engine, Path | None] = {}
    notes: list[str] = []
    ce_version = old.ce_version if old is not None else ""
    with tempfile.TemporaryDirectory() as tmp:
        for engine in ENGINES:
            previous = None if old is None else old.render(engine)
            if engine not in wanted and previous is not None:
                renders[engine] = previous
                continue
            fresh = Path(tmp) / f"{engine}.mkv"
            result = engines.run(case, engine, video=fresh)
            if result.source is not None and result.source != source:
                msg = f"{case.name}: scene.py changed while it rendered"
                raise RuntimeError(msg)
            if engine == "ce":
                ce_version = result.manim or importlib.metadata.version("manim")
            video = case.video(engine)
            frames = renders[engine] = result.frames
            if isinstance(frames, Failure):
                placed[engine] = None
                notes.append(f"{engine} failed: {frames.error}")
            elif (
                engine == "manimgx"
                and current
                and isinstance(previous, Frames)
                and video.exists()
                and _looks_same(video, previous, fresh, frames)
            ):
                renders[engine] = previous
                same = "unchanged" if previous == frames else "looks the same"
                notes.append(f"{engine} {same}")
            elif (
                engine == "ce"
                and isinstance(previous, Frames)
                and previous.runs == frames.runs
                and video.exists()
                and case.ce_hash.exists()
                and case.ce_hash.read_text(encoding="ascii") == _identity(video)
            ):
                notes.append(f"{engine} unchanged")
            else:
                placed[engine] = videos[engine] = fresh
                notes.append(f"{engine} {'new' if previous is None else 'changed'}")
        kept = (
            old.comparison
            if old is not None and all(renders[e] == old.render(e) for e in ENGINES)
            else None
        )
        facts = _facts(case, source, renders, videos, ce_version, kept)
        for engine, made in placed.items():
            video = case.video(engine)
            if made is None:
                video.unlink(missing_ok=True)
            else:
                shutil.move(made, video)
            if engine == "ce":
                if made is None:
                    case.ce_hash.unlink(missing_ok=True)
                else:
                    case.ce_hash.write_text(_identity(video), encoding="ascii")
        case.write_facts(facts)
    return facts, "; ".join(notes)


def _looks_same(reference: Path, facts: Frames, fresh: Path, frames: Frames) -> bool:
    """Whether a fresh render keeps the times of ManimGX's reference and looks the same,
    frame by frame. A reference video that is not the film its facts record looks like
    nothing."""
    if not facts.timed_like(frames):
        return False
    different: list[Difference] = []
    try:
        with closing(Movie(reference, facts)) as movie:
            comparison = FrameComparison(
                movie, lambda difference, *_: different.append(difference)
            )
            for index, pixels in enumerate(decode(fresh, SIZE)):
                comparison.add(index, 1, pixels.tobytes())
    except ValueError:  # (the reference video is not its facts' film)
        return False
    return not different


def _identity(video: Path) -> str:
    """A video's identity, as its sidecar records it: the hash of its bytes, and its name."""
    return f"{hashlib.sha256(video.read_bytes()).hexdigest()}  {video.name}\n"


def recompare(case: Case) -> str:
    """Compare a case's references again (after the metrics changed)."""
    facts = case.facts()
    if facts is None:
        return "not rendered"
    renders: dict[Engine, Frames | Failure] = {"manimgx": facts.manimgx, "ce": facts.ce}
    videos = {engine: case.video(engine) for engine in ENGINES}
    facts = _facts(case, facts.source, renders, videos, facts.ce_version, kept=None)
    case.write_facts(facts)
    return "compared" if facts.comparison is not None else "nothing to compare"


def _facts(
    case: Case,
    source: str,
    renders: dict[Engine, Frames | Failure],
    videos: dict[Engine, Path],
    ce_version: str,
    kept: Comparison | None,
) -> Facts:
    """The facts of these renders, compared (unless `kept`) through these videos."""
    manimgx, ce = renders["manimgx"], renders["ce"]
    comparison = None
    if isinstance(manimgx, Frames) and isinstance(ce, Frames):
        if kept is None:
            missing = [engine for engine in ENGINES if not videos[engine].exists()]
            if missing:
                msg = (
                    f"{case.name}: reference video(s) missing ({', '.join(missing)}); "
                    f"run `just corpus render {case.name}` to regenerate them"
                )
                raise FileNotFoundError(msg)
        comparison = kept or comparing.compare(
            ce, manimgx, videos["ce"], videos["manimgx"], SIZE, FPS
        )
    return Facts(
        source=source,
        size=SIZE,
        fps=FPS,
        manimgx=manimgx,
        ce=ce,
        ce_version=ce_version,
        comparison=comparison,
    )
