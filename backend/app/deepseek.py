from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.providers import ActiveModelConfig

SYSTEM_PROMPT = """你是 CodeBugger 的代码调试智能体 BugHunter。
请基于用户提供的信息定位问题，并给出清晰、可执行的排查步骤或修复方案。
信息不足时明确说明缺少什么，不要编造项目文件、运行结果或已经完成的操作。
回答默认使用中文，代码和命令保持原始语法。"""


class ModelServiceError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class _CompletionMessage(BaseModel):
    content: str | None = None


class _CompletionChoice(BaseModel):
    message: _CompletionMessage


class _CompletionResponse(BaseModel):
    choices: list[_CompletionChoice]


class ModelClient:
    def __init__(
        self,
        config: ActiveModelConfig,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self.transport = transport

    async def generate_reply(self, message: str, max_tokens: int | None = None) -> str:
        return await self._request_completion(message, max_tokens=max_tokens)

    async def validate_connection(self) -> None:
        await self._request_completion(
            "请回复 OK",
            max_tokens=32,
            allow_empty_content=True,
        )

    async def _request_completion(
        self,
        message: str,
        max_tokens: int | None = None,
        allow_empty_content: bool = False,
    ) -> str:
        if self.config.api_key is None:
            raise ModelServiceError(
                status_code=503,
                detail=f"{self.config.provider_name} API Key 未配置，请先在模型设置中填写。",
            )

        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
            "temperature": self.config.temperature,
            "max_tokens": max_tokens or self.config.max_tokens,
            "stream": False,
        }
        headers = {
            "Authorization": (
                f"Bearer {self.config.api_key.get_secret_value()}"
            ),
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                timeout=self.config.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise ModelServiceError(
                504,
                f"{self.config.provider_name} 响应超时，请稍后重试。",
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelServiceError(
                502,
                f"无法连接 {self.config.provider_name} 服务。",
            ) from exc

        if response.status_code in {401, 403}:
            raise ModelServiceError(
                502,
                f"{self.config.provider_name} 认证失败，请检查 API Key。",
            )
        if response.status_code == 429:
            raise ModelServiceError(
                429,
                f"{self.config.provider_name} 请求过于频繁，请稍后重试。",
            )
        if response.is_error:
            raise ModelServiceError(
                502,
                f"{self.config.provider_name} 服务返回异常状态（{response.status_code}）。",
            )

        try:
            completion = _CompletionResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise ModelServiceError(
                502,
                f"{self.config.provider_name} 返回了无法解析的响应。",
            ) from exc

        if not completion.choices:
            raise ModelServiceError(502, f"{self.config.provider_name} 未返回回答。")

        content = completion.choices[0].message.content
        if not content or not content.strip():
            if allow_empty_content:
                return ""
            raise ModelServiceError(502, f"{self.config.provider_name} 返回了空回答。")
        return content.strip()


# Keep the old names import-compatible for existing local integrations.
DeepSeekServiceError = ModelServiceError
DeepSeekClient = ModelClient
