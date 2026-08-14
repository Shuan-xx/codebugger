import asyncio
import io
import json
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.context import ProjectContext, ProjectContextStore
from app.deepseek import ModelServiceError
from app.main import (
    app,
    get_agent_models,
    get_context_store,
    get_model_client,
    get_model_config_store,
    get_test_runner,
)
from app.providers import ModelConfigStore
from app.sandbox import SafeTestRunner
from app.settings import Settings


class StubDeepSeekClient:
    async def generate_reply(
        self,
        message: str,
        max_tokens: int | None = None,
        system_prompt: str = "",
    ) -> str:
        del max_tokens, system_prompt
        return f"模型已处理：{message}"

    async def stream_reply(self, message: str, system_prompt: str = ""):
        del message, system_prompt
        for chunk in ("分析", "完成"):
            yield chunk

    async def validate_connection(self) -> None:
        return None


class FailingDeepSeekClient:
    async def generate_reply(self, message: str, max_tokens: int | None = None) -> str:
        del message, max_tokens
        raise ModelServiceError(504, "DeepSeek 响应超时，请稍后重试。")

    async def validate_connection(self) -> None:
        raise ModelServiceError(504, "DeepSeek 响应超时，请稍后重试。")


class FailingStreamClient(StubDeepSeekClient):
    async def stream_reply(self, message: str, system_prompt: str = ""):
        del message, system_prompt
        if False:
            yield ""
        raise ModelServiceError(502, "模型流式响应失败。")


@pytest.fixture(autouse=True)
def isolated_model_store() -> Iterator[None]:
    store = ModelConfigStore(Settings(_env_file=None))
    app.dependency_overrides[get_model_config_store] = lambda: store
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(_env_file=None)
    app.dependency_overrides[get_model_client] = StubDeepSeekClient
    app.dependency_overrides[get_agent_models] = lambda: {
        "bughunter": StubDeepSeekClient(),
        "codeanalyst": StubDeepSeekClient(),
        "testrunner": StubDeepSeekClient(),
    }
    app.dependency_overrides[get_context_store] = lambda: ProjectContextStore(
        settings,
        root=tmp_path / "contexts",
    )
    app.dependency_overrides[get_test_runner] = lambda: SafeTestRunner(settings)
    with TestClient(app) as test_client:
        yield test_client
    for dependency in (
        get_model_client,
        get_agent_models,
        get_context_store,
        get_test_runner,
    ):
        app.dependency_overrides.pop(dependency, None)


def test_health_check(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["model"] == "deepseek-v4-flash"


def test_chat_returns_model_reply(client: TestClient) -> None:
    response = client.post("/api/chat", json={"message": "  定位登录报错  "})

    assert response.status_code == 200
    assert response.json() == {
        "reply": "模型已处理：定位登录报错",
        "agent_name": "BugHunter",
        "status": "completed",
    }


def test_chat_rejects_blank_message(client: TestClient) -> None:
    response = client.post("/api/chat", json={"message": "   "})

    assert response.status_code == 422


def test_chat_maps_model_timeout_to_http_error() -> None:
    app.dependency_overrides[get_model_client] = FailingDeepSeekClient
    try:
        with TestClient(app) as test_client:
            response = test_client.post("/api/chat", json={"message": "测试超时"})
    finally:
        app.dependency_overrides.pop(get_model_client, None)

    assert response.status_code == 504
    assert response.json()["detail"] == "DeepSeek 响应超时，请稍后重试。"


def test_settings_reads_requested_environment_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK-APIKEY-CODEBUGGER", "test-secret")

    settings = Settings(_env_file=None)

    assert settings.deepseek_api_key is not None
    assert settings.deepseek_api_key.get_secret_value() == "test-secret"


def test_model_config_masks_user_api_key(client: TestClient) -> None:
    response = client.put(
        "/api/model-config",
        json={
            "provider": "kimi",
            "model": "kimi-k2.5",
            "api_key": "sk-example-super-secret-1234",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "kimi"
    assert body["configured"] is True
    assert body["api_key_masked"].startswith("sk-")
    assert body["api_key_masked"].endswith("1234")
    assert "example-super-secret" not in response.text


def test_model_config_switches_provider_for_health(client: TestClient) -> None:
    client.put(
        "/api/model-config",
        json={"provider": "aliyun", "model": "qwen-plus", "api_key": "test-key-123"},
    )

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["provider"] == "aliyun"
    assert response.json()["model"] == "qwen-plus"
    assert response.json()["model_configured"] is True


def test_model_config_lists_zhipu_provider(client: TestClient) -> None:
    response = client.get("/api/model-config")

    provider_ids = {item["id"] for item in response.json()["providers"]}
    assert "zhipu" in provider_ids


def test_model_connection_endpoint_returns_success(client: TestClient) -> None:
    response = client.post("/api/model-config/test")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "message": "模型服务连接成功"}


def test_each_agent_has_independent_masked_model_config(client: TestClient) -> None:
    response = client.put(
        "/api/agents/codeanalyst/model-config",
        json={"provider": "kimi", "model": "kimi-k2.5", "api_key": "secret-kimi-key"},
    )

    assert response.status_code == 200
    codeanalyst = response.json()
    assert codeanalyst["agent_id"] == "codeanalyst"
    assert codeanalyst["provider"] == "kimi"
    assert codeanalyst["configured"] is True
    assert "secret-kimi-key" not in response.text

    configs = client.get("/api/agents/model-config").json()
    bughunter = next(item for item in configs if item["agent_id"] == "bughunter")
    assert bughunter["provider"] == "deepseek"


def test_project_context_accepts_source_files(client: TestClient) -> None:
    response = client.post(
        "/api/context",
        files=[("files", ("src/app.py", b"print('ok')", "text/x-python"))],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["context_id"]
    assert body["files"] == [
        {"path": "src/app.py", "size": 11, "language": "python"},
    ]


def test_project_context_has_no_file_count_limit(client: TestClient) -> None:
    files = [
        ("files", (f"src/file_{index}.py", b"x=1", "text/x-python"))
        for index in range(55)
    ]

    response = client.post("/api/context", files=files)

    assert response.status_code == 200
    assert len(response.json()["files"]) == 55


def test_project_context_rejects_zip_traversal(client: TestClient) -> None:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("../escape.py", "print('no')")

    response = client.post(
        "/api/context",
        files=[("files", ("project.zip", archive.getvalue(), "application/zip"))],
    )

    assert response.status_code == 400
    assert "路径不安全" in response.json()["detail"]


def test_multi_agent_stream_runs_agents_in_order(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.orchestrator.SUPERVISOR_INTAKE_SECONDS", 0)
    monkeypatch.setattr("app.orchestrator.REPORT_READY_SECONDS", 0)
    monkeypatch.setattr("app.orchestrator.AGENT_HANDOFF_SECONDS", 0)
    monkeypatch.setattr("app.orchestrator.FINAL_DELIVERY_SECONDS", 0)
    response = client.post(
        "/api/chat/stream",
        json={"message": "定位问题", "run_tests": False},
    )

    assert response.status_code == 200
    events = [
        json.loads(block.removeprefix("data: "))
        for block in response.text.strip().split("\n\n")
    ]
    working_agents = [
        event["agent"]
        for event in events
        if event["type"] == "agent_status" and event["status"] == "working"
    ]
    assert working_agents == ["bughunter", "codeanalyst", "testrunner"]
    assert [event["type"] for event in events].count("handoff") == 2
    assert [event["type"] for event in events].count("final_delivery") == 1
    assert events[-2]["type"] == "final_delivery"
    assert events[-1]["type"] == "done"


def test_multi_agent_stream_emits_model_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.orchestrator.SUPERVISOR_INTAKE_SECONDS", 0)
    app.dependency_overrides[get_agent_models] = lambda: {
        "bughunter": FailingStreamClient(),
        "codeanalyst": StubDeepSeekClient(),
        "testrunner": StubDeepSeekClient(),
    }

    response = client.post(
        "/api/chat/stream",
        json={"message": "触发错误", "run_tests": False},
    )

    assert response.status_code == 200
    assert '"type": "error"' in response.text
    assert "模型流式响应失败" in response.text


def test_safe_runner_does_not_expose_api_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK-APIKEY-CODEBUGGER", "must-not-leak")
    root = tmp_path / "project"
    root.mkdir()
    (root / "example.py").write_text("print('ok')", encoding="utf-8")
    context = ProjectContext(
        id="test",
        root=root,
        files=(),
        total_bytes=0,
        created_at=0,
    )
    runner = SafeTestRunner(Settings(_env_file=None))

    result = asyncio.run(runner.run(context, "python-compile"))

    assert result.status == "passed"
    assert "must-not-leak" not in result.output
