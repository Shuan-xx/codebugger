import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.context import ProjectContext, ProjectContextStore
from app.deepseek import ModelClient
from app.sandbox import SafeTestRunner, TestCommandId, TestExecutionResult


@dataclass(frozen=True)
class AgentDefinition:
    id: str
    name: str
    role: str
    system_prompt: str


AGENTS = (
    AgentDefinition(
        id="bughunter",
        name="BugHunter",
        role="定位异常与根因",
        system_prompt="""你是 CoDebugger 团队中的 BugHunter，负责第一阶段故障定位。
结合用户描述和真实项目文件，输出：问题摘要、最可能根因、证据、需要进一步核实的信息。
不要编造不存在的文件、代码或测试结果。使用 Markdown，结论要具体、简洁、可交接给下一位智能体。""",
    ),
    AgentDefinition(
        id="codeanalyst",
        name="CodeAnalyst",
        role="审查代码与设计修复",
        system_prompt="""你是 CoDebugger 团队中的 CodeAnalyst，负责第二阶段代码审查与修复设计。
基于用户问题、项目文件和 BugHunter 的分析，指出具体文件和代码风险，给出可实施修改。
如果信息足够，使用 fenced ```diff 代码块提供 unified diff；信息不足时给出精确修改步骤，禁止虚构已修改文件。
使用 Markdown，输出要能直接交给 TestRunner 验证。""",
    ),
    AgentDefinition(
        id="testrunner",
        name="TestRunner",
        role="执行验证与交付结论",
        system_prompt="""你是 CoDebugger 团队中的 TestRunner，负责第三阶段验证与最终交付。
综合用户问题、BugHunter 根因分析、CodeAnalyst 修复建议和真实命令执行结果。
明确区分已验证、未验证和验证失败的内容；不得声称执行了未执行的测试。
使用 Markdown 输出：验证结果、残余风险、建议命令、最终修复清单。""",
    ),
)

SUPERVISOR_INTAKE_SECONDS = 4.8
REPORT_READY_SECONDS = 0.35
AGENT_HANDOFF_SECONDS = 2.75
FINAL_DELIVERY_SECONDS = 3.4


class MultiAgentOrchestrator:
    def __init__(
        self,
        context_store: ProjectContextStore,
        test_runner: SafeTestRunner,
    ) -> None:
        self.context_store = context_store
        self.test_runner = test_runner

    async def run(
        self,
        *,
        message: str,
        models: dict[str, ModelClient],
        context: ProjectContext | None,
        run_tests: bool,
        test_command: TestCommandId,
    ) -> AsyncIterator[dict[str, object]]:
        context_text = self.context_store.prompt_text(context)
        outputs: dict[str, str] = {}
        test_result: TestExecutionResult | None = None

        yield {
            "type": "task_started",
            "agent_count": len(AGENTS),
            "context_files": len(context.files) if context else 0,
        }
        await asyncio.sleep(SUPERVISOR_INTAKE_SECONDS)

        for index, agent in enumerate(AGENTS):
            model = models[agent.id]
            yield {
                "type": "agent_status",
                "agent": agent.id,
                "agent_name": agent.name,
                "role": agent.role,
                "status": "working",
                "stage": index + 1,
            }

            if agent.id == "testrunner":
                if run_tests:
                    test_result = await self.test_runner.run(context, test_command)
                else:
                    test_result = TestExecutionResult(
                        command_id=test_command,
                        command="",
                        status="skipped",
                        exit_code=None,
                        duration_ms=0,
                        output="用户未启用本次安全测试执行。",
                    )
                yield {"type": "test_result", **test_result.model_dump()}

            prompt = self._build_prompt(
                agent=agent,
                message=message,
                context_text=context_text,
                outputs=outputs,
                test_result=test_result,
            )
            chunks: list[str] = []
            async for chunk in model.stream_reply(prompt, system_prompt=agent.system_prompt):
                chunks.append(chunk)
                yield {
                    "type": "token",
                    "agent": agent.id,
                    "agent_name": agent.name,
                    "content": chunk,
                }

            content = "".join(chunks).strip()
            outputs[agent.id] = content
            yield {
                "type": "agent_complete",
                "agent": agent.id,
                "agent_name": agent.name,
                "content": content,
                "stage": index + 1,
            }

            if index < len(AGENTS) - 1:
                await asyncio.sleep(REPORT_READY_SECONDS)
                target = AGENTS[index + 1]
                yield {
                    "type": "handoff",
                    "from_agent": agent.id,
                    "from_name": agent.name,
                    "to_agent": target.id,
                    "to_name": target.name,
                    "message": f"{agent.name} 已完成，正在向 {target.name} 交接任务。",
                }
                await asyncio.sleep(AGENT_HANDOFF_SECONDS)
            else:
                await asyncio.sleep(REPORT_READY_SECONDS)
                yield {
                    "type": "final_delivery",
                    "agent": agent.id,
                    "agent_name": agent.name,
                    "message": f"{agent.name} 已完成最终报告，正在离开 LAB 并交付结果。",
                }
                await asyncio.sleep(FINAL_DELIVERY_SECONDS)

        yield {
            "type": "done",
            "status": "completed",
            "reply": outputs.get("testrunner", ""),
            "agents": list(outputs),
        }

    @staticmethod
    def _build_prompt(
        *,
        agent: AgentDefinition,
        message: str,
        context_text: str,
        outputs: dict[str, str],
        test_result: TestExecutionResult | None,
    ) -> str:
        previous = "\n\n".join(
            f"## {name}\n{content[:18_000]}"
            for name, content in (
                ("BugHunter 交接结果", outputs.get("bughunter", "")),
                ("CodeAnalyst 交接结果", outputs.get("codeanalyst", "")),
            )
            if content
        )
        test_section = ""
        if test_result is not None:
            test_section = (
                "\n\n## 真实测试执行结果\n"
                f"状态：{test_result.status}\n"
                f"命令：{test_result.command or '未执行'}\n"
                f"退出码：{test_result.exit_code}\n"
                f"耗时：{test_result.duration_ms}ms\n"
                f"输出：\n```text\n{test_result.output[:12_000]}\n```"
            )
        return (
            f"# 用户调试任务\n{message}\n\n"
            f"# 项目上下文\n{context_text}\n\n"
            f"# 上游智能体结果\n{previous or '这是流水线第一阶段。'}"
            f"{test_section}\n\n"
            f"请以 {agent.name} 的职责完成当前阶段，不要重复无关背景。"
        )
