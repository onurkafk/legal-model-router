import pytest

from legal_router import core


@pytest.fixture(autouse=True)
def no_user_config(tmp_path, monkeypatch):
    """Tests never read the developer's own key, decision model or config file."""
    monkeypatch.setattr(core, "CONFIG", tmp_path / "config.json")
    monkeypatch.delenv("LEGAL_ROUTER_CLASSIFIER", raising=False)
