import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEEPSEEK_API_KEY_ENV = "DEEPSEEK-APIKEY-CODEBUGGER"


def _read_windows_persisted_environment(name: str) -> str | None:
    """Read a persisted variable when the current terminal predates the change."""

    if os.name != "nt":
        return None

    import winreg

    locations = (
        (winreg.HKEY_CURRENT_USER, "Environment"),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ),
    )
    for root, path in locations:
        try:
            with winreg.OpenKey(root, path) as key:
                value, _ = winreg.QueryValueEx(key, name)
        except OSError:
            continue
        if isinstance(value, str) and value.strip():
            return value
    return None


class Settings(BaseSettings):
    deepseek_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=DEEPSEEK_API_KEY_ENV,
    )
    deepseek_base_url: str = Field(
        default="https://api.deepseek.com",
        validation_alias="DEEPSEEK_BASE_URL",
    )
    deepseek_model: str = Field(
        default="deepseek-v4-flash",
        validation_alias="DEEPSEEK_MODEL",
    )
    deepseek_timeout_seconds: float = Field(
        default=60,
        gt=0,
        le=300,
        validation_alias="DEEPSEEK_TIMEOUT_SECONDS",
    )
    deepseek_temperature: float = Field(
        default=0.2,
        ge=0,
        le=2,
        validation_alias="DEEPSEEK_TEMPERATURE",
    )
    deepseek_max_tokens: int = Field(
        default=2048,
        ge=1,
        le=8192,
        validation_alias="DEEPSEEK_MAX_TOKENS",
    )

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("deepseek_api_key", mode="before")
    @classmethod
    def normalize_api_key(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def has_deepseek_api_key(self) -> bool:
        return self.deepseek_api_key is not None


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.deepseek_api_key is None:
        persisted_key = _read_windows_persisted_environment(DEEPSEEK_API_KEY_ENV)
        if persisted_key:
            settings.deepseek_api_key = SecretStr(persisted_key)
    return settings
