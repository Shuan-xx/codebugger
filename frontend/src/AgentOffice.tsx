import { BatteryCharging, Bug, Check, Code2, FileText, FlaskConical, Settings2 } from 'lucide-react'
import type { AgentId, AgentModelConfig } from './api'

export type AgentRuntimeStatus = 'idle' | 'working' | 'complete' | 'error'

type Handoff = { from: AgentId; to: AgentId } | null

type AgentOfficeProps = {
  statuses: Record<AgentId, AgentRuntimeStatus>
  configs: Partial<Record<AgentId, AgentModelConfig>>
  handoff: Handoff
  returningAgent: AgentId | null
  intakeActive: boolean
  finalDeliveryActive: boolean
  onConfigure: (agentId: AgentId) => void
}

const agents: Array<{
  id: AgentId
  name: string
  role: string
}> = [
  { id: 'bughunter', name: 'BugHunter', role: '故障定位与根因分析' },
  { id: 'codeanalyst', name: 'CodeAnalyst', role: '代码审查与修复设计' },
  { id: 'testrunner', name: 'TestRunner', role: '安全测试与验证交付' },
]

const statusText: Record<AgentRuntimeStatus, string> = {
  idle: '待机充电',
  working: '正在工作',
  complete: '阶段完成',
  error: '执行异常',
}

function Robot({ status, variant }: { status: AgentRuntimeStatus; variant: AgentId }) {
  const VariantIcon = variant === 'bughunter' ? Bug : variant === 'codeanalyst' ? Code2 : FlaskConical

  return (
    <div className={`office-robot ${variant} ${status}`} aria-hidden="true">
      <span className="robot-antenna"><i /></span>
      <span className="robot-antenna secondary"><i /></span>
      <span className="robot-head"><i className="robot-eye left" /><i className="robot-eye right" /><i className="robot-mouth" /></span>
      <span className="robot-neck" />
      <span className="robot-body"><VariantIcon size={16} /><i /></span>
      <span className="robot-arm left" /><span className="robot-arm right" />
      <span className="robot-leg left" /><span className="robot-leg right" />
      <span className="robot-charge-port"><BatteryCharging size={10} /></span>
      <svg className="robot-charge-cable" viewBox="0 0 64 96" focusable="false">
        <path className="charge-wire" d="M53 4 C42 20 50 34 37 46 S8 59 12 88" />
        <path className="charge-current" d="M53 4 C42 20 50 34 37 46 S8 59 12 88" />
      </svg>
      <span className="charging-outlet"><i /><i /></span>
      <span className="robot-report"><b>REPORT</b><i /><i /><i /></span>
    </div>
  )
}

function SupervisorRobot() {
  return (
    <div className="supervisor-robot" aria-hidden="true">
      <span className="supervisor-antenna"><i /></span>
      <span className="supervisor-head"><i className="left" /><i className="right" /><b /></span>
      <span className="supervisor-body"><i className="supervisor-tie" /><b>LEAD</b></span>
      <span className="supervisor-arm left" /><span className="supervisor-arm right" />
      <span className="supervisor-leg left" /><span className="supervisor-leg right" />
      <span className="supervisor-brief"><FileText size={13} /><b>TASK</b><i /><i /></span>
    </div>
  )
}

export default function AgentOffice({
  statuses,
  configs,
  handoff,
  returningAgent,
  intakeActive,
  finalDeliveryActive,
  onConfigure,
}: AgentOfficeProps) {
  const handoffClass = handoff ? `${handoff.from}-to-${handoff.to}` : ''
  const returnClass = returningAgent ? `${returningAgent}-returning` : ''

  return (
    <section className="agent-office" aria-label="多智能体协作办公室">
      <div className="office-heading">
        <div>
          <span>LIVE AGENT OFFICE</span>
          <h2>协同调试办公室</h2>
        </div>
        <p><span className="live-dot" />点击机器人配置其专属模型</p>
      </div>

      <div className="office-scene">
        <div className="office-wall-grid" aria-hidden="true" />
        <div className="office-window" aria-hidden="true"><i /><i /><span>CoDebugger LAB</span></div>
        <div className="office-clock" aria-hidden="true"><i /><b /></div>
        <div className="office-door" aria-hidden="true"><span>LAB</span><i /></div>
        <div className="office-floor" aria-hidden="true" />

        <div className={`supervisor-route ${intakeActive ? 'active' : ''}`} aria-hidden="true">
          <SupervisorRobot />
          <span className="supervisor-speech">新调试任务<br />请先定位根因</span>
        </div>

        <div className="agent-routes" aria-hidden="true">
          <div className={`handoff-runner ${handoffClass}`}>
            <Robot status="complete" variant={handoff?.from ?? 'bughunter'} />
            <span className="handoff-packet"><FileText size={13} /><b>REPORT</b><i /><i /></span>
          </div>
          <div className={`return-runner ${returnClass}`}>
            <Robot status="idle" variant={returningAgent ?? 'bughunter'} />
          </div>
          <div className={`final-delivery-runner ${finalDeliveryActive ? 'active' : ''}`}>
            <Robot status="complete" variant="testrunner" />
            <span className="delivery-label">FINAL REPORT</span>
          </div>
        </div>

        <div className="office-stations">
          {agents.map((agent, index) => {
            const config = configs[agent.id]
            const status = statuses[agent.id]
            return (
              <button
                className={`office-station station-${index + 1} ${status} ${handoff?.from === agent.id ? 'is-handing-off' : ''} ${handoff?.to === agent.id ? 'is-receiving' : ''} ${returningAgent === agent.id ? 'is-returning' : ''} ${finalDeliveryActive && agent.id === 'testrunner' ? 'is-final-delivering' : ''} ${intakeActive && agent.id === 'bughunter' ? 'receiving-task' : ''}`}
                type="button"
                key={agent.id}
                onClick={() => onConfigure(agent.id)}
                aria-label={`${agent.name}，${agent.role}，${config?.configured ? `${config.provider_name} ${config.model}` : '模型未配置'}，点击配置模型`}
              >
                <span className="station-status"><i />{intakeActive && agent.id === 'bughunter' ? '主管交付中' : statusText[status]}</span>
                {agent.id === 'bughunter' && <span className="agent-task-reply">收到，开始分析</span>}
                <span className="office-monitor">
                  <span className="monitor-top"><i /><i /><i /></span>
                  <span className="monitor-screen"><b>{index === 0 ? '&gt; trace --live' : index === 1 ? '{ fix: ready }' : '✓ tests'}</b><i /><i /><i /></span>
                  <span className="monitor-stand" />
                </span>
                <span className="office-chair"><i className="chair-back" /><i className="chair-seat" /><i className="chair-post" /><i className="chair-wheel left" /><i className="chair-wheel right" /></span>
                <Robot status={status} variant={agent.id} />
                <span className="office-desk"><i className="desk-edge" /><i className="desk-leg left" /><i className="desk-leg right" /></span>
                <span className="desk-nameplate">
                  <strong>{agent.name}</strong>
                  <span className="agent-hover-card" role="tooltip">
                    <span className="hover-card-kicker">AGENT PROFILE</span>
                    <b>{agent.name}</b>
                    <small>{agent.role}</small>
                    <span className="hover-card-line"><i className={`status-dot ${status}`} />{intakeActive && agent.id === 'bughunter' ? '正在接收主管任务' : statusText[status]}</span>
                    <span className={`hover-card-model ${config?.configured ? 'configured' : ''}`}>
                      {config?.configured ? <Check size={13} /> : <Settings2 size={13} />}
                      {config?.configured ? `${config.provider_name} · ${config.model}` : '模型尚未配置'}
                    </span>
                  </span>
                </span>
              </button>
            )
          })}
        </div>
      </div>
    </section>
  )
}
