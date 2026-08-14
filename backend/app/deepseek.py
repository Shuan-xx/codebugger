import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.providers import ActiveModelConfig

SYSTEM_PROMPT = """你是 CoDebugger 的代码调试智能体 BugHunter。
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

    async def generate_reply(
        self,
        message: str,
        max_tokens: int | None = None,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> str:
        return await self._request_completion(
            message,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
        )

    async def stream_reply(
        self,
        message: str,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> AsyncIterator[str]:
        self._require_api_key()
        payload = self._payload(message, system_prompt, stream=True)
        yielded = False

        try:
            async with httpx.AsyncClient(
                timeout=self.config.timeout_seconds,
                transport=self.transport,
            ) as client, client.stream(
                "POST",
                self._url,
                headers=self._headers,
                json=payload,
            ) as response:
                self._raise_for_status(response)
                content_type = response.headers.get("content-type", "")
                if "text/event-stream" not in content_type:
                    raw = await response.aread()
                    content = self._parse_completion(raw)
                    if content:
                        yield content
                        return
                    raise ModelServiceError(
                        502,
                        f"{self.config.provider_name} 返回了空回答。",
                    )

                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        event = json.loads(data)
                    except ValueError:
                        continue
                    content = self._stream_content(event)
                    if content:
                        yielded = True
                        yield content
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

        if not yielded:
            raise ModelServiceError(502, f"{self.config.provider_name} 返回了空回答。")

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
        system_prompt: str = SYSTEM_PROMPT,
    ) -> str:
        self._require_api_key()
        payload = self._payload(
            message,
            system_prompt,
            stream=False,
            max_tokens=max_tokens,
        )

        try:
            async with httpx.AsyncClient(
                timeout=self.config.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    self._url,
                    headers=self._headers,
                    json=payload,
                )
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

        self._raise_for_status(response)
        content = self._parse_completion(response.content)
        if not content:
            if allow_empty_content:
                return ""
            raise ModelServiceError(502, f"{self.config.provider_name} 返回了空回答。")
        return content

    def _payload(
        self,
        message: str,
        system_prompt: str,
        *,
        stream: bool,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        return {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
            "temperature": self.config.temperature,
            "max_tokens": max_tokens or self.config.max_tokens,
            "stream": stream,
        }

    def _require_api_key(self) -> None:
        if self.config.api_key is None:
            raise ModelServiceError(
                status_code=503,
                detail=f"{self.config.provider_name} API Key 未配置，请先在模型设置中填写。",
            )

    def _raise_for_status(self, response: httpx.Response) -> None:
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

    def _parse_completion(self, raw: bytes) -> str:
        try:
            completion = _CompletionResponse.model_validate_json(raw)
        except (ValueError, ValidationError) as exc:
            raise ModelServiceError(
                502,
                f"{self.config.provider_name} 返回了无法解析的响应。",
            ) from exc
        if not completion.choices:
            raise ModelServiceError(502, f"{self.config.provider_name} 未返回回答。")
        content = completion.choices[0].message.content
        return content.strip() if content and content.strip() else ""

    @staticmethod
    def _stream_content(event: object) -> str:
        if not isinstance(event, dict):
            return ""
        choices = event.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        choice = choices[0]
        if not isinstance(choice, dict):
            return ""
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            return ""
        content = delta.get("content")
        return content if isinstance(content, str) else ""

    @property
    def _url(self) -> str:
        return f"{self.config.base_url.rstrip('/')}/chat/completions"

    @property
    def _headers(self) -> dict[str, str]:
        api_key = self.config.api_key
        if api_key is None:
            return {}
        return {
            "Authorization": f"Bearer {api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }


# Keep the old names import-compatible for existing local integrations.
DeepSeekServiceError = ModelServiceError
DeepSeekClient = ModelClient
