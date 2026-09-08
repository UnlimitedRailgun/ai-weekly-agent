from unittest.mock import Mock

import pytest
from pydantic import ValidationError

import ai_weekly_agent.config as config_module
from ai_weekly_agent.config import (
    AppConfig,
    create_openai_client,
    load_config,
)


def configured_app(**overrides: object) -> AppConfig:
    values = {
        "openai_api_key": "test-key-not-a-real-credential",
        "openai_model": "test-model",
        **overrides,
    }
    return AppConfig(**values)


def test_config_loads_without_openai_credentials() -> None:
    config = load_config(env={})

    assert config.openai_api_key is None
    assert config.openai_model is None
    assert config.openai_max_retries is None
    assert config.openai_timeout_seconds is None


def test_config_reads_supplied_environment_values() -> None:
    config = load_config(
        env={
            "OPENAI_API_KEY": "test-key-not-a-real-credential",
            "OPENAI_MODEL": "test-model",
        }
    )

    assert config.openai_api_key == "test-key-not-a-real-credential"
    assert config.openai_model == "test-model"


def test_config_reads_retry_and_timeout_values() -> None:
    config = load_config(
        env={
            "OPENAI_MAX_RETRIES": "3",
            "OPENAI_TIMEOUT_SECONDS": "45.5",
        }
    )

    assert config.openai_max_retries == 3
    assert config.openai_timeout_seconds == 45.5


def test_blank_reliability_values_are_unset() -> None:
    config = load_config(
        env={
            "OPENAI_MAX_RETRIES": "  ",
            "OPENAI_TIMEOUT_SECONDS": "",
        }
    )

    assert config.openai_max_retries is None
    assert config.openai_timeout_seconds is None


@pytest.mark.parametrize("value", ["0", "1", "5"])
def test_retry_count_accepts_zero_and_positive_integers(value: str) -> None:
    config = load_config(env={"OPENAI_MAX_RETRIES": value})

    assert config.openai_max_retries == int(value)


def test_negative_retry_count_is_rejected() -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        load_config(env={"OPENAI_MAX_RETRIES": "-1"})


@pytest.mark.parametrize("value", ["1.5", "many"])
def test_non_integer_retry_count_is_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="OPENAI_MAX_RETRIES must be an integer"):
        load_config(env={"OPENAI_MAX_RETRIES": value})


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1", 1.0), ("0.25", 0.25), ("120.5", 120.5)],
)
def test_timeout_accepts_positive_integer_and_decimal_values(
    value: str, expected: float
) -> None:
    config = load_config(env={"OPENAI_TIMEOUT_SECONDS": value})

    assert config.openai_timeout_seconds == expected


@pytest.mark.parametrize("value", ["0", "-0.1"])
def test_non_positive_timeout_is_rejected(value: str) -> None:
    with pytest.raises(ValidationError, match="greater than 0"):
        load_config(env={"OPENAI_TIMEOUT_SECONDS": value})


@pytest.mark.parametrize("value", ["soon", "1 second"])
def test_nonnumeric_timeout_is_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="OPENAI_TIMEOUT_SECONDS must be numeric"):
        load_config(env={"OPENAI_TIMEOUT_SECONDS": value})


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_non_finite_timeout_is_rejected(value: str) -> None:
    with pytest.raises(ValidationError, match="finite number"):
        load_config(env={"OPENAI_TIMEOUT_SECONDS": value})


@pytest.mark.parametrize(
    ("overrides", "expected_kwargs"),
    [
        ({}, {}),
        ({"openai_max_retries": 3}, {"max_retries": 3}),
        ({"openai_timeout_seconds": 20.5}, {"timeout": 20.5}),
        (
            {"openai_max_retries": 4, "openai_timeout_seconds": 30.0},
            {"max_retries": 4, "timeout": 30.0},
        ),
        ({"openai_max_retries": 0}, {"max_retries": 0}),
    ],
)
def test_client_factory_passes_only_configured_sdk_options(
    overrides: dict[str, object],
    expected_kwargs: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_client = object()
    constructor = Mock(return_value=expected_client)
    monkeypatch.setattr(config_module, "OpenAI", constructor)
    config = configured_app(**overrides)

    client = create_openai_client(config)

    assert client is expected_client
    constructor.assert_called_once_with(
        api_key="test-key-not-a-real-credential",
        **expected_kwargs,
    )


def test_openai_configuration_is_validated_only_when_requested() -> None:
    config = load_config(env={})

    with pytest.raises(ValueError, match="OPENAI_API_KEY, OPENAI_MODEL"):
        config.require_openai_configuration()
