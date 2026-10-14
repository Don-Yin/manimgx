"""Deployment credentials reach only main, with its own configuration, and nothing is
previewed."""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
WORKFLOWS = {
    path.stem: yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"]
    for path in sorted((ROOT / ".github/workflows").glob("*.yaml"))
}


def test_docs_snapshots_can_resume_failures_and_save_repairs() -> None:
    steps = WORKFLOWS["deploy-docs"]["build"]["steps"]
    restore, save = [
        step for step in steps if step.get("uses", "").startswith("actions/cache/")
    ]
    # An immutable exact hit must never prevent saving a repaired or extended set.
    # Prefix lookup selects the latest attempt for the same inventory first.
    assert restore["with"]["path"] == save["with"]["path"]
    prefix = "${{ steps.films.outputs.key }}-"
    assert restore["with"]["key"] == prefix
    assert save["with"]["key"].startswith(prefix)
    assert "github.run_id" in save["with"]["key"]
    assert "github.run_attempt" in save["with"]["key"]
    condition = save["if"]
    assert "always()" in condition  # failure and cancellation must reach the save step
    assert "github.ref == 'refs/heads/main'" in condition
    assert "cache-hit" not in condition
    assert "steps.completed.outcome == 'success'" in condition
    assert "hashFiles('docs/.cache/films/*.json') != ''" in condition
    before = next(step for step in steps if step.get("id") == "restored")
    after = next(step for step in steps if step.get("id") == "completed")
    assert before["run"] == after["run"]
    assert "--cache-state" in before["run"]
    assert "always()" in after["if"]
    assert "steps.restored.outcome == 'success'" in after["if"]
    assert "steps.completed.outputs.state != steps.restored.outputs.state" in condition


@pytest.mark.parametrize(
    ("workflow", "build", "publish", "assets"),
    [
        ("deploy-docs", "build", "deploy", "docs/site"),
        ("test", "coverage", "publish-coverage", "htmlcov"),
    ],
)
def test_build_artifacts_cannot_supply_the_deployment_configuration(
    workflow: str, build: str, publish: str, assets: str
) -> None:
    jobs = WORKFLOWS[workflow]
    upload = next(
        step["with"]
        for step in jobs[build]["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert upload["path"].rstrip("/") == assets
    steps = jobs[publish]["steps"]
    checkout = next(
        step["with"]
        for step in steps
        if step.get("uses", "").startswith("actions/checkout@")
    )
    assert "ref" not in checkout  # the configuration of the commit it publishes, main's
    assert checkout["sparse-checkout"] == ".github/deploy"
    assert checkout["persist-credentials"] is False
    download = next(
        step["with"]
        for step in steps
        if step.get("uses", "").startswith("actions/download-artifact@")
    )
    assert download["path"] == assets
    # Even a build that puts its own .github/deploy tree in the artifact cannot
    # replace the trusted configuration at the workspace root.
    injected_config = ROOT / download["path"] / ".github/deploy/docs.jsonc"
    assert not injected_config.is_relative_to(ROOT / ".github/deploy")


def test_only_main_gets_the_deployment_credentials() -> None:
    credentialed = {
        (workflow, name): job
        for workflow, jobs in WORKFLOWS.items()
        for name, job in jobs.items()
        if "secrets.CLOUDFLARE_API_TOKEN" in str(job)
    }
    assert set(credentialed) == {
        ("deploy-docs", "deploy"),
        ("test", "publish-coverage"),
    }
    for job in credentialed.values():
        assert "github.ref == 'refs/heads/main'" in job["if"]
        # the production environments, which admit only main
        assert job["environment"]["name"] in {"docs", "coverage"}


def test_nothing_is_previewed() -> None:
    for jobs in WORKFLOWS.values():
        for job in jobs.values():
            assert "preview" not in str(job.get("environment", ""))
            for step in job.get("steps", []):
                assert not re.search(r"wrangler\S*\s+preview\b", step.get("run", ""))
    # nor is any version of a site served on workers.dev
    for site in ("docs", "coverage"):
        config = (ROOT / f".github/deploy/{site}.jsonc").read_text(encoding="utf-8")
        assert re.search(r'"preview_urls":\s*false', config)
        assert '"previews"' not in config
