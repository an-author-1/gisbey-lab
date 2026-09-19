import pytest

from gibsey_lab.config import Config, load_config

ALL_RELEVANT_VARS = ("TYPESAFE_API_KEY", "TYPESAFE_MODEL", "JEV_API_KEY", "JEV_MODEL", "JEV_MODEL_ID")


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Never let a real repo .env or real shell env leak into these tests."""
    for var in ALL_RELEVANT_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("gibsey_lab.config.ENV_PATH", tmp_path / "nonexistent.env")


def test_load_config_prefers_typesafe_model_env(monkeypatch):
    monkeypatch.setenv("TYPESAFE_MODEL", "jev-pinned")
    monkeypatch.setenv("TYPESAFE_API_KEY", "sk-test-should-not-leak")
    cfg = load_config()
    assert cfg.model == "jev-pinned"
    assert cfg.has_live_credentials is True


def test_load_config_defaults_to_jev_latest():
    cfg = load_config()
    assert cfg.model == "jev-latest"
    assert cfg.has_live_credentials is False


def test_already_exported_env_vars_are_not_overridden_by_dotenv(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("TYPESAFE_MODEL=from-dotenv\n")
    monkeypatch.setattr("gibsey_lab.config.ENV_PATH", env_file)
    monkeypatch.setenv("TYPESAFE_MODEL", "from-real-environment")
    cfg = load_config()
    assert cfg.model == "from-real-environment"


def test_legacy_jev_api_key_is_accommodated_not_discarded(monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "sk-legacy-value")
    monkeypatch.setenv("JEV_MODEL_ID", "jev-legacy-model")
    cfg = load_config()
    assert cfg.has_live_credentials is True
    assert cfg.model == "jev-legacy-model"


def test_api_key_never_appears_in_repr_or_str():
    cfg = Config(model="jev-latest", api_key="sk-super-secret-value")
    assert "sk-super-secret-value" not in repr(cfg)
    assert "sk-super-secret-value" not in str(cfg)
