import pytest

from ai_weekly_agent.config import load_config


def test_config_loads_without_openai_credentials() -> None:
    config = load_config(env={})

    assert config.openai_api_key is None
    assert config.openai_model is None


def test_config_reads_supplied_environment_values() -> None:
    config = load_config(
        env={
            "OPENAI_API_KEY": "test-key-not-a-real-credential",
            "OPENAI_MODEL": "test-model",
        }
    )

    assert config.openai_api_key == "test-key-not-a-real-credential"
    assert config.openai_model == "test-model"


def test_openai_configuration_is_validated_only_when_requested() -> None:
    config = load_config(env={})

    with pytest.raises(ValueError, match="OPENAI_API_KEY, OPENAI_MODEL"):
        config.require_openai_configuration()
