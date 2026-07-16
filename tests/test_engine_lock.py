import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_engine_lock_is_full_immutable_commit_sha():
    assert re.fullmatch(r"[0-9a-f]{40}\n?", (ROOT / "engine.lock").read_text())


def test_every_app_checkout_consumes_the_resolved_lock():
    workflows = "\n".join(
        path.read_text() for path in sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    )
    app_checkouts = workflows.count("repository: ${{ env.APP_REPO }}")
    assert app_checkouts == 3
    assert workflows.count("ref: ${{ steps.engine.outputs.sha }}") == app_checkouts
    assert workflows.count("Resolve immutable engine revision") == app_checkouts
