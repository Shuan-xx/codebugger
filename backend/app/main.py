import asyncio
import json
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.context import ContextUploadError, ProjectContextResponse, ProjectContextStore
from app.deepseek import ModelClient, ModelServiceError
from app.orchestrator import MultiAgentOrchestrator
from app.providers import (
    AGENT_NAMES,
    AgentId,
    ModelConfigStore,
    ModelConfigUpdate,
    PublicAgentModelConfig,
    PublicModelConfig,
)
from app.sandbox import SafeTestRunner, TestCommandId
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


class MultiAgentChatRequest(ChatRequest):
    context_id: str | None = Field(default=None, max_length=64)
    run_tests: bool = True
    test_command: TestCommandId = "auto"


@lru_cache
def get_model_config_store() -> ModelConfigStore:
    return ModelConfigStore(get_settings())


@lru_cache
def get_context_store() -> ProjectContextStore:
    return ProjectContextStore(get_settings())


@lru_cache
def get_test_runner() -> SafeTestRunner:
    return SafeTestRunner(get_settings())


ModelConfigDependency = Annotated[ModelConfigStore, Depends(get_model_config_store)]
ContextStoreDependency = Annotated[ProjectContextStore, Depends(get_context_store)]
TestRunnerDependency = Annotated[SafeTestRunner, Depends(get_test_runner)]


def get_model_client(store: ModelConfigDependency) -> ModelClient:
    return ModelClient(store.snapshot())


ModelDependency = Annotated[ModelClient, Depends(get_model_client)]


def get_agent_models(store: ModelConfigDependency) -> dict[str, ModelClient]:
    return {
        agent_id: ModelClient(store.snapshot(agent_id))
        for agent_id in AGENT_NAMES
    }


AgentModelsDependency = Annotated[dict[str, ModelClient], Depends(get_agent_models)]


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


@app.get("/api/agents/model-config", response_model=list[PublicAgentModelConfig])
def read_agent_model_configs(
    store: ModelConfigDependency,
) -> list[PublicAgentModelConfig]:
    """Return masked model settings for every office agent."""

    return store.public_agents()


@app.get(
    "/api/agents/{agent_id}/model-config",
    response_model=PublicAgentModelConfig,
)
def read_agent_model_config(
    agent_id: AgentId,
    store: ModelConfigDependency,
) -> PublicAgentModelConfig:
    return store.public_agent(agent_id)


@app.put(
    "/api/agents/{agent_id}/model-config",
    response_model=PublicAgentModelConfig,
)
def update_agent_model_config(
    agent_id: AgentId,
    update: ModelConfigUpdate,
    store: ModelConfigDependency,
) -> PublicAgentModelConfig:
    store.update(update, agent_id)
    return store.public_agent(agent_id)


@app.post("/api/agents/{agent_id}/model-config/test")
async def test_agent_model_config(
    agent_id: AgentId,
    store: ModelConfigDependency,
) -> dict[str, str]:
    model = ModelClient(store.snapshot(agent_id))
    try:
        await model.validate_connection()
    except ModelServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {
        "status": "ok",
        "message": f"{AGENT_NAMES[agent_id]} 模型连接成功",
    }


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


@app.post("/api/context", response_model=ProjectContextResponse)
async def upload_project_context(
    context_store: ContextStoreDependency,
    files: Annotated[list[UploadFile], File(...)],
) -> ProjectContextResponse:
    """Accept source files or ZIP archives as temporary task context."""

    try:
        return await context_store.create(files)
    except ContextUploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _encode_sse(event: dict[str, object]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.post("/api/chat/stream")
async def stream_chat(
    request: MultiAgentChatRequest,
    models: AgentModelsDependency,
    context_store: ContextStoreDependency,
    test_runner: TestRunnerDependency,
) -> StreamingResponse:
    """Run the real three-agent pipeline and stream typed progress events."""

    context = context_store.get(request.context_id)
    if request.context_id and context is None:
        raise HTTPException(status_code=404, detail="项目上下文已过期或不存在，请重新上传。")

    orchestrator = MultiAgentOrchestrator(context_store, test_runner)

    async def event_stream():
        try:
            async for event in orchestrator.run(
                message=request.message,
                models=models,
                context=context,
                run_tests=request.run_tests,
                test_command=request.test_command,
            ):
                yield _encode_sse(event)
        except asyncio.CancelledError:
            raise
        except ModelServiceError as exc:
            yield _encode_sse(
                {
                    "type": "error",
                    "status_code": exc.status_code,
                    "message": exc.detail,
                }
            )
        except Exception:  # noqa: BLE001 - keep the SSE contract after headers are sent.
            yield _encode_sse(
                {
                    "type": "error",
                    "status_code": 500,
                    "message": "多智能体任务执行失败，请检查后端日志。",
                }
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
