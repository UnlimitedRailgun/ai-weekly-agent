"""Environment-based application configuration."""

from collections.abc import Mapping
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field


class AppConfig(BaseModel):
    """Configuration that may be loaded without API credentials."""

    model_config = ConfigDict(str_strip_whitespace=True)

    openai_api_key: str | None = Field(default=None, repr=False)
    openai_model: str | None = None
    openai_max_retries: int | None = Field(default=None, ge=0)
    openai_timeout_seconds: float | None = Field(
        default=None,
        gt=0,
        allow_inf_nan=False,
    )

    def require_openai_configuration(self) -> None:
        """Raise when a future API-dependent operation lacks configuration."""
        missing = []
        if not self.openai_api_key:
            missing.append("OPENAI_API_KEY")
        if not self.openai_model:
            missing.append("OPENAI_MODEL")

        if missing:
            names = ", ".join(missing)
            raise ValueError(f"Missing required OpenAI configuration: {names}")


def load_config(
    env: Mapping[str, str] | None = None,
    *,
    load_env_file: bool = True,
) -> AppConfig:
    """Load configuration from a mapping or the current environment."""
    if env is None:
        if load_env_file:
            load_dotenv()
        env = os.environ

    return AppConfig(
        openai_api_key=env.get("OPENAI_API_KEY") or None,
        openai_model=env.get("OPENAI_MODEL") or None,
        openai_max_retries=_optional_integer(env, "OPENAI_MAX_RETRIES"),
        openai_timeout_seconds=_optional_number(
            env, "OPENAI_TIMEOUT_SECONDS"
        ),
    )


def create_openai_client(config: AppConfig) -> OpenAI:
    """Create an SDK client while preserving defaults for unset options."""
    config.require_openai_configuration()
    options: dict[str, Any] = {"api_key": config.openai_api_key}
    if config.openai_max_retries is not None:
        options["max_retries"] = config.openai_max_retries
    if config.openai_timeout_seconds is not None:
        options["timeout"] = config.openai_timeout_seconds
    return OpenAI(**options)


def _optional_integer(env: Mapping[str, str], name: str) -> int | None:
    value = _optional_value(env, name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _optional_number(env: Mapping[str, str], name: str) -> float | None:
    value = _optional_value(env, name)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc


def _optional_value(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
