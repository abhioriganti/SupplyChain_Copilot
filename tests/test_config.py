from pathlib import Path

import pytest

from supplychain_copilot import config
from supplychain_copilot.config import ConfigError, load_settings

ENV_VARS = [
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_ROLE",
    "SNOWFLAKE_WAREHOUSE",
    "SNOWFLAKE_DATABASE",
    "SNOWFLAKE_PRIVATE_KEY_PATH",
    "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE",
]


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    # point .env lookup at an empty temp dir so a developer's real .env is never read
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path / "repo")
    return monkeypatch


def _set_valid(monkeypatch, key_file: Path) -> None:
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "myorg-myaccount")
    monkeypatch.setenv("SNOWFLAKE_USER", "scc_svc")
    monkeypatch.setenv("SNOWFLAKE_ROLE", "SCC_DEV_ROLE")
    monkeypatch.setenv("SNOWFLAKE_WAREHOUSE", "SCC_WH")
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "SCC_DB")
    monkeypatch.setenv("SNOWFLAKE_PRIVATE_KEY_PATH", str(key_file))


def test_missing_vars_are_listed(clean_env):
    with pytest.raises(ConfigError) as exc:
        load_settings()
    assert "SNOWFLAKE_ACCOUNT" in str(exc.value)
    assert "SNOWFLAKE_PRIVATE_KEY_PATH" in str(exc.value)


def test_valid_settings_are_normalised(clean_env, tmp_path):
    key = tmp_path / "outside" / "key.p8"
    key.parent.mkdir()
    key.write_text("dummy")
    _set_valid(clean_env, key)

    s = load_settings()

    assert s.account == "MYORG-MYACCOUNT"
    assert s.user == "SCC_SVC"
    assert s.account_url == "https://myorg-myaccount.snowflakecomputing.com"


def test_repr_hides_key_material(clean_env, tmp_path):
    key = tmp_path / "k.p8"
    key.write_text("dummy")
    _set_valid(clean_env, key)
    clean_env.setenv("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE", "super-secret-pass")

    text = repr(load_settings())

    assert "super-secret-pass" not in text
    assert str(key) not in text


def test_key_inside_project_is_rejected(clean_env, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    key = repo / "key.p8"
    key.write_text("dummy")
    _set_valid(clean_env, key)

    with pytest.raises(ConfigError, match="outside the project"):
        load_settings()


@pytest.mark.parametrize("bad", ["SCC;DROP", "1ROLE", "role name"])
def test_identifier_injection_is_rejected(clean_env, tmp_path, bad):
    key = tmp_path / "k.p8"
    key.write_text("dummy")
    _set_valid(clean_env, key)
    clean_env.setenv("SNOWFLAKE_ROLE", bad)

    with pytest.raises(ConfigError, match="SNOWFLAKE_ROLE"):
        load_settings()
