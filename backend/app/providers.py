from dataclasses import dataclass
from threading import RLock
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator

from app.settings import Settings

ProviderId = Literal["aliyun", "deepseek", "minimax", "xiaomi", "kimi", "zhipu"]


@dataclass(frozen=True)
class ProviderDefinition:
    id: ProviderId
    name: str
    base_url: str
    default_model: str
    accent: str


PROVIDERS: dict[ProviderId, ProviderDefinition] = {
    "aliyun": ProviderDefinition(
        id="aliyun",
        name="阿里百炼",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen-plus",
        accent="#ff6a00",
    ),
    "deepseek": ProviderDefinition(
        id="deepseek",
        name="DeepSeek",
        base_url="https://api.deepseek.com",
        default_model="deepseek-v4-flash",
        accent="#4d6bfe",
    ),
    "minimax": ProviderDefinition(
        id="minimax",
        name="MiniMax",
        base_url="https://api.minimaxi.com/v1",
        default_model="MiniMax-M2.1",
        accent="#e846a8",
    ),
    "xiaomi": ProviderDefinition(
        id="xiaomi",
        name="小米 MiMo",
        base_url="https://api.xiaomimimo.com/v1",
        default_model="mimo-v2-flash",
        accent="#ff6900",
    ),
    "kimi": ProviderDefinition(
        id="kimi",
        name="Kimi",
        base_url="https://api.moonshot.cn/v1",
        default_model="kimi-k2.5",
        accent="#111827",
    ),
    "zhipu": ProviderDefinition(
        id="zhipu",
        name="智谱",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-5",
        accent="#345cff",
    ),
}


class ProviderOption(BaseModel):
    id: ProviderId
    name: str
    default_model: str
    accent: str
    configured: bool


class PublicModelConfig(BaseModel):
    provider: ProviderId
    provider_name: str
    model: str
    base_url: str
    configured: bool
    api_key_masked: str | None
    providers: list[ProviderOption]


class ModelConfigUpdate(BaseModel):
    provider: ProviderId
    model: str | None = Field(default=None, min_length=1, max_length=120)
    api_key: SecretStr | None = Field(default=None)

    @field_validator("model", mode="before")
    @classmethod
    def normalize_model(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("api_key", mode="before")
    @classmethod
    def normalize_api_key(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if value and len(value) < 6:
                raise ValueError("API Key 长度不能少于 6 位")
            return value or None
        return value


@dataclass(frozen=True)
class ActiveModelConfig:
    provider: ProviderId
    provider_name: str
    base_url: str
    model: str
    api_key: SecretStr | None
    timeout_seconds: float
    temperature: float
    max_tokens: int


def mask_api_key(api_key: SecretStr | None) -> str | None:
    if api_key is None:
        return None
    value = api_key.get_secret_value()
    if len(value) <= 8:
        return "•" * len(value)
    prefix_length = min(3, len(value) - 5)
    return f"{value[:prefix_length]}{'•' * 14}{value[-4:]}"


class ModelConfigStore:
    """Keep user-supplied keys in backend memory and never return raw values."""

    def __init__(self, settings: Settings) -> None:
        self._lock = RLock()
        self._active_provider: ProviderId = "deepseek"
        self._api_keys: dict[ProviderId, SecretStr] = {}
        if settings.deepseek_api_key is not None:
            self._api_keys["deepseek"] = settings.deepseek_api_key
        self._models: dict[ProviderId, str] = {
            provider_id: definition.default_model
            for provider_id, definition in PROVIDERS.items()
        }
        self._models["deepseek"] = settings.deepseek_model
        self._base_urls: dict[ProviderId, str] = {
            provider_id: definition.base_url
            for provider_id, definition in PROVIDERS.items()
        }
        self._base_urls["deepseek"] = settings.deepseek_base_url
        self._timeout_seconds = settings.deepseek_timeout_seconds
        self._temperature = settings.deepseek_temperature
        self._max_tokens = settings.deepseek_max_tokens

    def update(self, update: ModelConfigUpdate) -> PublicModelConfig:
        with self._lock:
            self._active_provider = update.provider
            if update.model:
                self._models[update.provider] = update.model
            if update.api_key is not None:
                self._api_keys[update.provider] = update.api_key
            return self._public_locked()

    def snapshot(self) -> ActiveModelConfig:
        with self._lock:
            provider = PROVIDERS[self._active_provider]
            return ActiveModelConfig(
                provider=provider.id,
                provider_name=provider.name,
                base_url=self._base_urls[provider.id],
                model=self._models[provider.id],
                api_key=self._api_keys.get(provider.id),
                timeout_seconds=self._timeout_seconds,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )

    def public(self) -> PublicModelConfig:
        with self._lock:
            return self._public_locked()

    def _public_locked(self) -> PublicModelConfig:
        provider = PROVIDERS[self._active_provider]
        api_key = self._api_keys.get(provider.id)
        return PublicModelConfig(
            provider=provider.id,
            provider_name=provider.name,
            model=self._models[provider.id],
            base_url=self._base_urls[provider.id],
            configured=api_key is not None,
            api_key_masked=mask_api_key(api_key),
            providers=[
                ProviderOption(
                    id=item.id,
                    name=item.name,
                    default_model=item.default_model,
                    accent=item.accent,
                    configured=item.id in self._api_keys,
                )
                for item in PROVIDERS.values()
            ],
        )
