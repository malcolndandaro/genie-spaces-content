import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_every_space_has_required_canonical_audience_and_no_retired_sidecar():
    genie = ROOT / "src" / "genie"
    spaces = sorted(genie.glob("*.serialized_space.json"))
    assert spaces
    retired_suffix = "." + "access" + ".json"
    assert not list(genie.glob(f"*{retired_suffix}"))
    for space in spaces:
        slug = space.name.removesuffix(".serialized_space.json")
        audience_path = genie / f"{slug}.audience.json"
        assert audience_path.exists(), f"missing AudienceSpec for {slug}"
        payload = json.loads(audience_path.read_text())
        assert payload.keys() == {"principals"}
        assert payload["principals"]
        for principal in payload["principals"]:
            assert principal.keys() == {"principal", "is_group"}
            assert principal["principal"]
            assert "level" not in principal and "permission_level" not in principal


def test_workflows_use_locked_engine_revision_pair_and_audience_gate():
    pr = (ROOT / ".github" / "workflows" / "pr-checks.yml").read_text()
    deploy = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()
    combined = pr + deploy
    assert combined.count("ref: ${{ steps.engine.outputs.sha }}") == 3
    assert combined.count("scripts/content_revision.py app") == 3
    assert "scripts/check_audience.py" in pr
    assert ("scripts/check_" + "grants.py") not in pr
    assert "scripts/deploy_attempt.py" in deploy
    assert ("scripts/apply_" + "access.py") not in deploy
    assert "databricks bundle validate --strict" in pr
    # BOTH pr-checks jobs must scope the Genie gates to the spaces the PR changed (`validate` and
    # `eval-run`), and the `validate` job additionally scopes the dashboard gates to the dashboards it
    # changed. Asserting the two SCOPING FACTS beats asserting a raw call count, which changes every
    # time a resource kind is added.
    assert pr.count("-- 'src/genie/*'") == 2, "both Genie gate jobs must scope to the changed spaces"
    assert pr.count("-- 'src/dashboards/*'") == 1, \
        "the dashboard gates must scope to the changed dashboards"
    for suffix in ("serialized_space.json", "title", "mapping.json", "audience.json"):
        assert suffix in combined or "changed_space_slugs.py" in combined


def test_dashboard_gates_run_without_adding_a_required_check_or_an_app_checkout():
    """AI/BI dashboards are gated inside the EXISTING `bundle validate (prod)` job.

    Two invariants make that the right home and are worth pinning: the job NAMES are load-bearing for
    branch protection, and `test_engine_lock` requires exactly three app-repo checkouts — a fourth job
    would break both at once.
    """
    pr = (ROOT / ".github" / "workflows" / "pr-checks.yml").read_text()

    # The dashboard gates exist...
    assert "scripts/check_dashboard.py" in pr
    assert "scripts/check_dashboard_sql.py" in pr
    assert "--kind dashboard" in pr
    # ...and the required-check job names are unchanged.
    assert "name: bundle validate (prod)" in pr
    assert "name: eval-run pass-rate (dev)" in pr
    # A dashboard has no benchmarks, so the benchmark gates must NOT be pointed at one.
    assert "check_eval.py \"$f\"" not in pr.split("changed_dashboards")[-1]


def test_dashboard_sidecars_follow_the_same_contract_as_spaces():
    """Every promotable dashboard needs the same required sidecars a Space does: a non-empty title
    (it becomes display_name AND is the deploy's only id-resolution key) and a valid AudienceSpec.

    Dashboards use the NESTED layout — `src/dashboards/<area>/<name>/` with FIXED sidecar names inside
    (`dashboard.lvdash.json`, `title`, `audience.json`, optional `mapping.json`/`revision.json`) — so a
    business author browses the repo by the area that owns the painel. There is no version directory:
    git already holds the history, and a new revision replaces the same files.
    """
    dashboards = sorted((ROOT / "src" / "dashboards").glob("*/*/dashboard.lvdash.json"))
    assert dashboards, "expected at least one promotable dashboard"
    for artifact in dashboards:
        resource_dir = artifact.parent
        slug = f"{resource_dir.parent.name}/{resource_dir.name}"
        title = resource_dir / "title"
        audience = resource_dir / "audience.json"
        assert title.exists() and title.read_text(encoding="utf-8").strip(), f"{slug}: missing title"
        assert audience.exists(), f"{slug}: missing AudienceSpec"
        spec = json.loads(audience.read_text(encoding="utf-8"))
        assert set(spec) == {"principals"} and spec["principals"], f"{slug}: bad AudienceSpec"
        for principal in spec["principals"]:
            assert set(principal) == {"principal", "is_group"}, f"{slug}: bad principal shape"
            assert principal["principal"], f"{slug}: empty principal"
            assert "level" not in principal and "permission_level" not in principal


def test_no_dashboard_is_left_in_the_retired_flat_layout():
    """The flat `src/dashboards/<slug>.lvdash.json` shape is retired. A file left there would be
    silently INVISIBLE to render (which globs `*/*/dashboard.lvdash.json`) — deployed content that
    nobody notices stopped being deployed."""
    stray = sorted((ROOT / "src" / "dashboards").glob("*.lvdash.json"))
    assert not stray, f"migrate these to src/dashboards/<area>/<name>/: {[p.name for p in stray]}"


def test_every_dashboard_is_filed_under_a_path_safe_area():
    """The area is a directory AND part of a git branch + DABs resource key, so it must be safe by
    construction. The engine's controlled vocabulary is the gate; this is the content-side backstop."""
    import re

    for artifact in sorted((ROOT / "src" / "dashboards").glob("*/*/dashboard.lvdash.json")):
        area = artifact.parent.parent.name
        name = artifact.parent.name
        assert re.fullmatch(r"[a-z][a-z0-9_]{1,31}", area), f"unsafe area segment: {area!r}"
        assert re.fullmatch(r"[a-z][a-z0-9_]{0,47}", name), f"unsafe name segment: {name!r}"


def test_seed_has_no_retired_group_or_data_grant_mutation():
    seed = (ROOT / "src" / "setup" / "seed_recebiveis.py").read_text()
    assert ("consumer_" + "group") not in seed
    assert "GRANT USE" not in seed
    assert "GRANT SELECT" not in seed


def test_the_dashboard_gate_reads_the_nested_artifact_path_and_fails_closed():
    """REGRESSION: the gate loop must build the NESTED artifact path, and must FAIL on a miss.

    Observed live (run 30571328245): the loop built the retired flat path
    `build/dashboards/<slug>.lvdash.json`, so with a nested slug the file never existed, every gate
    `skip`ped, and `bundle validate (prod)` passed GREEN having validated nothing. A gate that cannot
    find its input must fail, not continue — the slug came from this PR's own diff.
    """
    pr = (ROOT / ".github" / "workflows" / "pr-checks.yml").read_text()
    # The gate step is the one that loops over the changed DASHBOARD slugs.
    marker = "for slug in ${{ steps.changed_dashboards.outputs.slugs }}"
    assert marker in pr, "the dashboard gate loop is missing"
    # Bound the slice at the loop's own `done`, or the Genie loop in the next JOB bleeds in.
    body = pr.split(marker, 1)[1]
    dashboard_step = body.split("\n          done", 1)[0]

    # The nested shape, with fixed sidecar names inside the resource directory.
    assert 'dir="build/dashboards/${slug}"' in dashboard_step
    assert 'f="${dir}/dashboard.lvdash.json"' in dashboard_step
    assert '"${dir}/audience.json"' in dashboard_step
    # The retired flat shape must not reappear.
    assert 'build/dashboards/${slug}.lvdash.json' not in pr
    assert 'build/dashboards/${slug}.audience.json' not in pr
    # And a missing artifact is a failure, not a skip.
    assert "exit 1" in dashboard_step
    assert "skip ${slug}" not in dashboard_step
