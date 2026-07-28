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
    """Every promotable dashboard needs the same required sidecars a Space does: a non-empty `.title`
    (it becomes display_name AND is the deploy's only id-resolution key) and a valid AudienceSpec."""
    dashboards = sorted((ROOT / "src" / "dashboards").glob("*.lvdash.json"))
    assert dashboards, "expected at least one promotable dashboard"
    for artifact in dashboards:
        slug = artifact.name[: -len(".lvdash.json")]
        title = artifact.with_name(f"{slug}.title")
        audience = artifact.with_name(f"{slug}.audience.json")
        assert title.exists() and title.read_text(encoding="utf-8").strip(), f"{slug}: missing title"
        assert audience.exists(), f"{slug}: missing AudienceSpec"
        spec = json.loads(audience.read_text(encoding="utf-8"))
        assert set(spec) == {"principals"} and spec["principals"], f"{slug}: bad AudienceSpec"
        for principal in spec["principals"]:
            assert set(principal) == {"principal", "is_group"}, f"{slug}: bad principal shape"
            assert principal["principal"], f"{slug}: empty principal"
            assert "level" not in principal and "permission_level" not in principal


def test_seed_has_no_retired_group_or_data_grant_mutation():
    seed = (ROOT / "src" / "setup" / "seed_recebiveis.py").read_text()
    assert ("consumer_" + "group") not in seed
    assert "GRANT USE" not in seed
    assert "GRANT SELECT" not in seed
