import pytest
from travel_agent.settings import Settings


def test_mock_defaults():
    settings = Settings.load()
    assert settings.mode == "mock"
    assert settings.bind_host == "127.0.0.1"
    assert settings.xhs_live_enabled is False
    assert settings.overview_budget == {"search_ops": 3, "detail_ops": 6, "vision_images": 2}


@pytest.mark.parametrize("override", [{"mode": "live"}, {"xhs_live_enabled": True}, {"bind_host": "0.0.0.0"}, {"preferred_port": 0}, {"preferred_port": True}])
def test_unsafe_settings_rejected(override):
    with pytest.raises(ValueError):
        Settings.load(**override)
