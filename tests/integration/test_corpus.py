"""The corpus's three checks, per case.

1. `test_same_source`: both references were rendered from this exact `scene.py`, which is the
   case's only code and reaches the engine only through `manimgx`'s top level (and its types,
   `manimgx.typing`) — so CE and ManimGX ran the same program. ManimGX's reference video is
   committed; CE's is identified by its sidecar.
2. `test_types`: the scene is type safe as written for ManimGX — `ty` with every rule, no
   escape from the checker, and no value ManimGX leaves `Any` or `Unknown`.
3. `test_regression`: today's ManimGX draws the scene as its reference shows it, whatever CE
   did and however the case was reviewed: as many frames, at the same scene times, each
   looking the same (within `frames.TOLERANCE` of the reference's), and the exported MP4
   holding every one. A scene whose pixels a machine's arithmetic decides is held to all but
   its pixels (`MACHINE_DEPENDENT`).

This module only checks. `python -m tests.integration.corpus` renders and reviews.
"""

import ast
import re
import shutil
from pathlib import Path

import pytest
from tests.integration.corpus import engines, typecheck
from tests.integration.corpus.case import (
    FPS,
    SIZE,
    Case,
    Failure,
    Frames,
    discover,
    seconds,
)
from tests.integration.corpus.frames import TOLERANCE

CASES = discover()
IDS = [case.name for case in CASES]
DIFFS = Path(__file__).resolve().parent / "_diffs"
# scenes whose pixels a machine's floating-point arithmetic decides, beyond any tolerance
MACHINE_DEPENDENT = {
    # two trajectories 0.001 apart: where chaos parts them depends on a machine's last bit
    "lorenz_attractor_dual_trajectory",
}


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_same_source(case: Case) -> None:
    others = sorted(p.name for p in case.dir.glob("*.py") if p.name != "scene.py")
    assert not others, f"a case has one source, scene.py; it also holds {others}"
    imported = _imported(ast.parse(case.scene.read_bytes()))
    direct = sorted({line for line, name in imported if name.split(".")[0] == "manim"})
    assert not direct, f"imports Manim CE directly (lines {direct}): use manimgx"
    inner = sorted(
        {
            line
            for line, name in imported
            if name.startswith("manimgx.") and name != "manimgx.typing"
        }
    )
    assert not inner, f"imports manimgx's modules (lines {inner}): use its top level"
    facts = case.facts()
    assert facts is not None, f"no references yet: just corpus render {case.name}"
    assert facts.source == case.source_hash(), (
        "scene.py changed since its references were rendered: "
        f"just corpus render {case.name}"
    )
    assert (facts.size, facts.fps) == (SIZE, FPS), "rendered at another size or rate"
    if isinstance(facts.manimgx, Frames):
        assert case.video("manimgx").exists(), "manimgx.mkv, its reference, is missing"
    if isinstance(facts.ce, Frames):
        sidecar = case.ce_hash
        assert sidecar.exists(), f"{sidecar.name} is missing"
        digest, separator, filename = (
            sidecar.read_text(encoding="ascii").strip().partition("  ")
        )
        assert separator == "  ", f"{sidecar.name} is malformed"
        assert filename == case.video("ce").name, f"{sidecar.name} is malformed"
        assert re.fullmatch(r"[0-9a-f]{64}", digest) is not None, (
            f"{sidecar.name} is malformed"
        )


def _imported(tree: ast.Module) -> list[tuple[int, str]]:
    """Each module a scene imports, with the line that imports it."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            found.append((node.lineno, node.module))
    return found


@pytest.fixture(scope="session")
def type_report() -> typecheck.TypeReport:
    return typecheck.report(CASES)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_types(case: Case, type_report: typecheck.TypeReport) -> None:
    problems = type_report.problems(case)
    if problems:
        pytest.fail("\n".join(problems), pytrace=False)


@pytest.mark.parametrize("case", CASES, ids=IDS)
@pytest.mark.timeout(0)  # engines.run owns each child's deadline and kills/reaps it.
def test_regression(case: Case) -> None:
    facts = case.facts()
    assert facts is not None, f"no references yet: just corpus render {case.name}"
    reference = facts.manimgx
    if isinstance(reference, Failure):
        pytest.fail(f"{case.name}: no reference: {reference.error}", pytrace=False)
    output = DIFFS / case.name
    output.mkdir(parents=True, exist_ok=True)
    result = engines.run(
        case,
        "manimgx",
        mp4=True,
        compare=case.name not in MACHINE_DEPENDENT,
        differences=output,
        log=output / "actual.log",
    )
    frames = result.frames
    if isinstance(frames, Failure):
        pytest.fail(f"{case.name}: {frames.error}; evidence: {output}", pytrace=False)
    if not frames.timed_like(reference):
        pytest.fail(
            f"{case.name}: {frames.count} frames over {seconds(frames.duration)} s, "
            f"where its reference shows {reference.count} over "
            f"{seconds(reference.duration)} s, or at other scene times",
            pytrace=False,
        )
    if result.mp4_frames != frames.count:
        pytest.fail(
            f"{case.name}: the exported MP4 holds {result.mp4_frames} of the film's "
            f"{frames.count} frames",
            pytrace=False,
        )
    if result.differences:
        changes = result.differences
        worst = max(changes, key=lambda d: d.amount)
        pytest.fail(
            f"{case.name}: {sum(d.repeat for d in changes)} frames look different from "
            f"its reference, from frame {changes[0].first} to "
            f"{changes[-1].first + changes[-1].repeat - 1}; they differ by as much as "
            f"{worst.amount:.0f} (frame {worst.first}), beyond the tolerance of "
            f"{TOLERANCE}; evidence: {output}",
            pytrace=False,
        )
    shutil.rmtree(output)
