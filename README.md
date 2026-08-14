# CoDebugger

CoDebugger 是一个基于 React、TypeScript 与 FastAPI 的 AI 多智能体代码调试工作台。当前已完成前后端聊天链路、真实服务健康检查，以及多家 OpenAI 兼容模型 API 的运行时配置。

## 名称与图标设计 / Naming and Icon

- **Code + Debugger**：`code-debugger` 表示这是一个面向代码问题定位、分析和修复的 Debug 工具。
- **Co + Debugger**：品牌名称采用 `CoDebugger`，其中 `Co` 代表 cooperation 与 collaboration，强调多个智能体、模型服务和调试工具的联合协同。
- **CD 虫形图标**：品牌图标把字母 `C` 和 `D` 组合成一只从顶部观察的虫子。较大的 `C` 构成虫子的身体与甲壳，较小的 `D` 构成带有双眼的头部，二者上下相连，既保留 `CD` 字母识别度，也直接呼应软件开发中的 Bug 与 Debug 概念。

The name combines two complementary meanings: **Code Debugger** describes the product as a code debugging tool, while **Co-Debugger** highlights coordinated work across multiple agents, model providers, and debugging tools. The artistic `CD` monogram forms a top-view bug: the larger `C` becomes the body and shell, and the smaller `D` becomes the head with two eyes, connecting the product identity directly to bugs and debugging.

## 已实现功能

- 前端通过 `POST /api/chat` 把调试问题发送给 FastAPI 后端，并展示模型回复、加载状态和失败重试。
- 每 8 秒检查一次后端状态；后端未启动时明确显示“服务离线”，恢复后自动更新为在线。
- 支持阿里百炼、DeepSeek、MiniMax、小米 MiMo、Kimi 和智谱六家模型服务。
- 支持在前端选择供应商、调整模型名称、填写 API Key，以及执行真实连接测试。
- API Key 使用密码输入框，后端仅返回大量遮蔽后的脱敏文本，不向浏览器回传明文。
- 用户填写的密钥只保存在当前后端进程内存中；后端重启后需要重新填写，避免写入浏览器缓存或项目文件。
- 模型连接测试使用独立的成功或失败弹窗，展示供应商、模型和可读的错误原因。
- 提供响应式桌面端和移动端界面，以及各供应商官方品牌图标。

## 项目结构

```text
codebugger/
├── backend/    FastAPI 后端、模型供应商配置和自动测试
└── frontend/   React + TypeScript + Vite 前端
```

## 环境配置

后端环境配置示例位于 `backend/.env.example`。默认 DeepSeek Key 可通过操作系统环境变量提供：

```dotenv
DEEPSEEK-APIKEY-CODEBUGGER=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_TIMEOUT_SECONDS=60
DEEPSEEK_TEMPERATURE=0.2
DEEPSEEK_MAX_TOKENS=2048
```

不要提交真实的 API Key。`backend/.env`、依赖目录、缓存和构建产物均已加入 Git 忽略规则。

## 启动后端

需要 Python 3.11 或更高版本：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

后端接口文档：`http://127.0.0.1:8000/docs`

## 启动前端

```powershell
cd frontend
npm install
npm run dev
```

默认前端地址：`http://127.0.0.1:5173`

Vite 会把 `/api` 请求代理到 `http://127.0.0.1:8000`。如需直连其他后端地址，可配置公开变量 `VITE_API_BASE_URL`，不要把 API Key 放入任何 `VITE_*` 变量。

## 验证

```powershell
cd backend
pytest
ruff check .

cd ..\frontend
npm run lint
npm run build
```
