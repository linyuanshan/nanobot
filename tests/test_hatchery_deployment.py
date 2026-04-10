from pathlib import Path

from hatchery.runtime_env import load_env_file
from hatchery.settings import HatcherySettings


def test_settings_from_env_loads_env_file_and_relay_map(monkeypatch, tmp_path: Path) -> None:
    relay_map_path = tmp_path / "relay-map.json"
    relay_map_path.write_text('{"feed":"relay_feed","emergency_stop":"relay_main"}', encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "HATCHERY_AUTH_ENABLED=true",
                'HATCHERY_AUTH_TOKENS_JSON={"admin-token":"admin"}',
                f"HATCHERY_REAL_RELAY_MAP_PATH={relay_map_path}",
                "HATCHERY_LOG_DIR=workspace/test-logs",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("HATCHERY_ENV_FILE", str(env_file))
    monkeypatch.delenv("HATCHERY_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("HATCHERY_AUTH_TOKENS_JSON", raising=False)
    monkeypatch.delenv("HATCHERY_REAL_RELAY_MAP_PATH", raising=False)
    monkeypatch.delenv("HATCHERY_REAL_RELAY_MAP_JSON", raising=False)
    monkeypatch.delenv("HATCHERY_LOG_DIR", raising=False)

    settings = HatcherySettings.from_env()

    assert settings.auth_enabled is True
    assert settings.auth_tokens == {"admin-token": "admin"}
    assert settings.real_relay_map["feed"] == "relay_feed"
    assert settings.log_dir == Path("workspace/test-logs")


def test_load_env_file_falls_back_to_example_when_default_env_is_missing(monkeypatch, tmp_path: Path) -> None:
    env_dir = tmp_path / "hatchery"
    env_dir.mkdir()
    example_file = env_dir / ".env.example"
    example_file.write_text(
        "\n".join(
            [
                "HATCHERY_MQTT_ENABLED=true",
                "HATCHERY_MQTT_HOST=127.0.0.1",
                "HATCHERY_MQTT_PORT=1883",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HATCHERY_ENV_FILE", raising=False)
    monkeypatch.delenv("HATCHERY_MQTT_ENABLED", raising=False)
    monkeypatch.delenv("HATCHERY_MQTT_HOST", raising=False)
    monkeypatch.delenv("HATCHERY_MQTT_PORT", raising=False)

    loaded = load_env_file()
    settings = HatcherySettings.from_env()

    assert loaded is not None
    assert loaded.resolve() == example_file.resolve()
    assert settings.mqtt_enabled is True
    assert settings.mqtt_host == "127.0.0.1"
    assert settings.mqtt_port == 1883

