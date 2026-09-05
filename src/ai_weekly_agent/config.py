"""Environment-based application configuration."""

from collections.abc import Mapping
import os

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field


class AppConfig(BaseModel):
    """Configuration that may be loaded without API credentials."""

    model_config = ConfigDict(str_strip_whitespace=True)

    openai_api_key: str | None = Field(default=None, repr=False)
    openai_model: str | None = None

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
    )
