from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.deepseek import ModelServiceError
from app.main import app, get_model_client, get_model_config_store
from app.providers import ModelConfigStore
from app.settings import Settings


class StubDeepSeekClient:
    async def generate_reply(self, message: str, max_tokens: int | None = None) -> str:
        del max_tokens
        return f"模型已处理：{message}"

    async def validate_connection(self) -> None:
        return None


class FailingDeepSeekClient:
    async def generate_reply(self, message: str, max_tokens: int | None = None) -> str:
        del message, max_tokens
        raise ModelServiceError(504, "DeepSeek 响应超时，请稍后重试。")

    async def validate_connection(self) -> None:
        raise ModelServiceError(504, "DeepSeek 响应超时，请稍后重试。")


@pytest.fixture(autouse=True)
def isolated_model_store() -> Iterator[None]:
    store = ModelConfigStore(Settings(_env_file=None))
    app.dependency_overrides[get_model_config_store] = lambda: store
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[get_model_client] = StubDeepSeekClient
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_model_client, None)


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
