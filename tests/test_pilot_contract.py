import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_every_space_has_required_canonical_audience_and_no_legacy_sidecar():
    genie = ROOT / "src" / "genie"
    spaces = sorted(genie.glob("*.serialized_space.json"))
    assert spaces
    assert not list(genie.glob("*.access.json"))
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
    assert "scripts/check_grants.py" not in pr
    assert "scripts/deploy_attempt.py" in deploy
    assert "scripts/apply_access.py" not in deploy
    assert "databricks bundle validate --strict" in pr
    assert pr.count("scripts/changed_space_slugs.py") == 2
    for suffix in ("serialized_space.json", "title", "mapping.json", "audience.json"):
        assert suffix in combined or "changed_space_slugs.py" in combined


def test_seed_has_no_consumer_group_or_uc_grant_mutation():
    seed = (ROOT / "src" / "setup" / "seed_recebiveis.py").read_text()
    assert "consumer_group" not in seed
    assert "GRANT USE" not in seed
    assert "GRANT SELECT" not in seed
