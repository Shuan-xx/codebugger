from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from app.deepseek import ModelClient, ModelServiceError
from app.providers import ModelConfigStore, ModelConfigUpdate, PublicModelConfig
from app.settings import get_settings


class ChatRequest(BaseModel):
    """前端发送给后端的聊天请求。"""

    message: str = Field(
        min_length=1,
        max_length=5000,
        description="用户输入的任务或问题",
    )

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        message = value.strip()
        if not message:
            raise ValueError("消息不能为空")
        return message


class ChatResponse(BaseModel):
    """后端返回给前端的聊天响应。"""

    reply: str
    agent_name: str
    status: str


@lru_cache
def get_model_config_store() -> ModelConfigStore:
    return ModelConfigStore(get_settings())


ModelConfigDependency = Annotated[ModelConfigStore, Depends(get_model_config_store)]


def get_model_client(store: ModelConfigDependency) -> ModelClient:
    return ModelClient(store.snapshot())


ModelDependency = Annotated[ModelClient, Depends(get_model_client)]


# Retain the old dependency name for compatible local tests and imports.
get_deepseek_client = get_model_client


app = FastAPI(
    title="CoDebugger AI Backend",
    description="CoDebugger AI 多智能体协同代码调试平台后端",
    version="0.3.0",
)

# Vite 代理使用同源请求；正则同时支持前端通过环境变量直连本地后端。
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict[str, str]:
    """返回后端基本信息。"""

    return {
        "name": "CoDebugger AI Backend",
        "version": "0.3.0",
        "message": "CoDebugger AI backend is running.",
        "docs": "/docs",
    }


@app.get("/api/health")
def health_check(store: ModelConfigDependency) -> dict[str, str | bool]:
    """检查后端服务以及模型配置状态。"""

    config = store.public()
    return {
        "status": "ok",
        "service": "codebugger-backend",
        "time": datetime.now(UTC).isoformat(),
        "provider": config.provider,
        "provider_name": config.provider_name,
        "model": config.model,
        "model_configured": config.configured,
    }


@app.get("/api/model-config", response_model=PublicModelConfig)
def read_model_config(store: ModelConfigDependency) -> PublicModelConfig:
    """Return runtime model settings without exposing any raw API key."""

    return store.public()


@app.put("/api/model-config", response_model=PublicModelConfig)
def update_model_config(
    update: ModelConfigUpdate,
    store: ModelConfigDependency,
) -> PublicModelConfig:
    """Select a provider and keep its user-supplied key in backend memory."""

    return store.update(update)


@app.post("/api/model-config/test")
async def test_model_config(model: ModelDependency) -> dict[str, str]:
    """Perform a small real provider call only when the user requests a test."""

    try:
        await model.validate_connection()
    except ModelServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"status": "ok", "message": "模型服务连接成功"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, model: ModelDependency) -> ChatResponse:
    """Send a user message to the currently selected model provider."""

    try:
        reply = await model.generate_reply(request.message)
    except ModelServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return ChatResponse(
        reply=reply,
        agent_name="BugHunter",
        status="completed",
    )
