from travel_agent.settings import RuntimePaths
import pytest


def test_runtime_containment(tmp_path):
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure()
    assert paths.database.parent == paths.root
    assert paths.profile.is_dir()
    for value in ("../secret", "../../outside", str(tmp_path / "outside")):
        with pytest.raises(ValueError):
            paths.child(value)


def test_runtime_cannot_target_source_tree():
    from travel_agent.settings import PROJECT_ROOT
    with pytest.raises(ValueError):
        RuntimePaths(PROJECT_ROOT / "apps").ensure()
