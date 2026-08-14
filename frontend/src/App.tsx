import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent, FormEvent, KeyboardEvent } from 'react'
import {
  ArrowUp,
  Bot,
  Bug,
  Check,
  Code2,
  FileCode2,
  FlaskConical,
  LoaderCircle,
  Menu,
  Paperclip,
  Plus,
  RefreshCw,
  RotateCcw,
  Settings2,
  ShieldCheck,
  Square,
  Wifi,
  WifiOff,
  X,
} from 'lucide-react'
import AgentOffice, { type AgentRuntimeStatus } from './AgentOffice'
import MarkdownMessage from './MarkdownMessage'
import ModelSettings from './ModelSettings'
import {
  ApiError,
  checkHealth,
  getAgentModelConfigs,
  streamDebugTask,
  uploadProjectFiles,
  type AgentId,
  type AgentModelConfig,
  type HealthResponse,
  type StreamEvent,
  type TestCommandId,
} from './api'
import './App.css'

type Message = {
  id: string
  role: 'user' | 'assistant' | 'error'
  content: string
  agentId?: AgentId
  agentName?: string
  originalMessage?: string
}

const agentMeta: Record<AgentId, { name: string; role: string; Icon: typeof Bug }> = {
  bughunter: { name: 'BugHunter', role: '定位异常与根因', Icon: Bug },
  codeanalyst: { name: 'CodeAnalyst', role: '审查代码与设计修复', Icon: Code2 },
  testrunner: { name: 'TestRunner', role: '执行验证与交付结论', Icon: FlaskConical },
}

const agentOrder: AgentId[] = ['bughunter', 'codeanalyst', 'testrunner']
const idleStatuses: Record<AgentId, AgentRuntimeStatus> = {
  bughunter: 'idle',
  codeanalyst: 'idle',
  testrunner: 'idle',
}
const RETURN_TO_CHARGE_MS = 2_200

const initialMessages: Message[] = [{
  id: 'welcome',
  role: 'assistant',
  agentName: 'CoDebugger Team',
  content: '### 多智能体调试工作台已就绪\n\n点击办公室中的机器人，为三个智能体分别配置模型。然后描述问题，也可以附加源码或 ZIP 项目包，团队会依次完成定位、修复设计和测试验证。',
}]

const testCommands: Array<{ value: TestCommandId; label: string }> = [
  { value: 'auto', label: '自动识别' },
  { value: 'python-compile', label: 'Python 编译检查' },
  { value: 'python-pytest', label: 'Pytest' },
  { value: 'npm-lint', label: 'npm lint' },
  { value: 'npm-test', label: 'npm test' },
  { value: 'npm-build', label: 'npm build' },
]

const formatBytes = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function App() {
  const [messages, setMessages] = useState<Message[]>(initialMessages)
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [isBackendOnline, setIsBackendOnline] = useState<boolean | null>(null)
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [configs, setConfigs] = useState<Partial<Record<AgentId, AgentModelConfig>>>({})
  const [agentStatuses, setAgentStatuses] = useState(idleStatuses)
  const [handoff, setHandoff] = useState<{ from: AgentId; to: AgentId } | null>(null)
  const [returningAgent, setReturningAgent] = useState<AgentId | null>(null)
  const [intakeActive, setIntakeActive] = useState(false)
  const [finalDeliveryActive, setFinalDeliveryActive] = useState(false)
  const [selectedAgent, setSelectedAgent] = useState<AgentId | null>(null)
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)
  const [files, setFiles] = useState<File[]>([])
  const [runTests, setRunTests] = useState(true)
  const [testCommand, setTestCommand] = useState<TestCommandId>('auto')
  const [uploadSummary, setUploadSummary] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const activeAgentRef = useRef<AgentId | null>(null)
  const returnTimerRef = useRef<number | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const messageEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const refreshConnection = useCallback(async () => {
    try {
      const nextHealth = await checkHealth()
      const nextConfigs = await getAgentModelConfigs()
      setHealth(nextHealth)
      setConfigs(Object.fromEntries(nextConfigs.map((config) => [config.agent_id, config])))
      setIsBackendOnline(true)
    } catch {
      setHealth(null)
      setIsBackendOnline(false)
    }
  }, [])

  useEffect(() => {
    const initialTimer = window.setTimeout(() => void refreshConnection(), 0)
    const timer = window.setInterval(() => void refreshConnection(), 8_000)
    const handleVisibility = () => {
      if (document.visibilityState === 'visible') void refreshConnection()
    }
    document.addEventListener('visibilitychange', handleVisibility)
    return () => {
      window.clearTimeout(initialTimer)
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', handleVisibility)
      abortRef.current?.abort()
      if (returnTimerRef.current !== null) window.clearTimeout(returnTimerRef.current)
    }
  }, [refreshConnection])

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isSending])

  useEffect(() => {
    const textarea = textareaRef.current
    if (!textarea) return
    textarea.style.height = 'auto'
    textarea.style.height = `${Math.min(textarea.scrollHeight, 150)}px`
  }, [input])

  const configuredCount = agentOrder.filter((id) => configs[id]?.configured).length
  const allAgentsConfigured = configuredCount === agentOrder.length
  const activeAgent = agentOrder.find((id) => agentStatuses[id] === 'working')
  const selectedConfig = selectedAgent ? configs[selectedAgent] ?? null : null

  const appendAgentToken = (taskId: string, event: Extract<StreamEvent, { type: 'token' }>) => {
    const messageId = `${taskId}-${event.agent}`
    setMessages((current) => {
      const found = current.some((item) => item.id === messageId)
      if (!found) {
        return [...current, {
          id: messageId,
          role: 'assistant',
          agentId: event.agent,
          agentName: event.agent_name,
          content: event.content,
        }]
      }
      return current.map((item) => item.id === messageId
        ? { ...item, content: item.content + event.content }
        : item)
    })
  }

  const handleStreamEvent = (taskId: string, event: StreamEvent) => {
    if (event.type === 'task_started') {
      setFinalDeliveryActive(false)
      setReturningAgent(null)
      setIntakeActive(true)
    } else if (event.type === 'agent_status') {
      const previousAgent = activeAgentRef.current
      setIntakeActive(false)
      activeAgentRef.current = event.agent
      setHandoff(null)
      if (previousAgent && previousAgent !== event.agent) {
        if (returnTimerRef.current !== null) window.clearTimeout(returnTimerRef.current)
        setReturningAgent(previousAgent)
        returnTimerRef.current = window.setTimeout(() => {
          setReturningAgent((current) => current === previousAgent ? null : current)
          returnTimerRef.current = null
        }, RETURN_TO_CHARGE_MS)
      }
      setAgentStatuses((current) => ({
        ...current,
        ...(previousAgent && previousAgent !== event.agent ? { [previousAgent]: 'idle' } : {}),
        [event.agent]: 'working',
      }))
      const messageId = `${taskId}-${event.agent}`
      setMessages((current) => current.some((item) => item.id === messageId) ? current : [
        ...current,
        { id: messageId, role: 'assistant', agentId: event.agent, agentName: event.agent_name, content: '' },
      ])
    } else if (event.type === 'token') {
      appendAgentToken(taskId, event)
    } else if (event.type === 'agent_complete') {
      setAgentStatuses((current) => ({ ...current, [event.agent]: 'complete' }))
    } else if (event.type === 'handoff') {
      setHandoff({ from: event.from_agent, to: event.to_agent })
    } else if (event.type === 'final_delivery') {
      setHandoff(null)
      setFinalDeliveryActive(true)
    } else if (event.type === 'test_result') {
      const command = event.command || '未执行'
      const report = `\n\n### 安全测试执行\n\n- 状态：**${event.status}**\n- 命令：\`${command}\`\n- 耗时：${event.duration_ms} ms\n\n\`\`\`text\n${event.output}\n\`\`\`\n\n`
      const messageId = `${taskId}-testrunner`
      setMessages((current) => current.map((item) => item.id === messageId
        ? { ...item, content: item.content + report }
        : item))
    }
  }

  const submitMessage = async (rawMessage: string, appendUser = true) => {
    const message = rawMessage.trim()
    if (!message || isSending) return
    if (isBackendOnline !== true) {
      setMessages((current) => [...current, {
        id: crypto.randomUUID(), role: 'error', content: '后端服务当前离线，请启动后端后重试。', originalMessage: message,
      }])
      return
    }
    const firstUnconfigured = agentOrder.find((id) => !configs[id]?.configured)
    if (firstUnconfigured) {
      setSelectedAgent(firstUnconfigured)
      return
    }

    if (appendUser) {
      const attachmentText = files.length ? `\n\n附件：${files.map((file) => file.name).join('、')}` : ''
      setMessages((current) => [...current, {
        id: crypto.randomUUID(), role: 'user', content: `${message}${attachmentText}`,
      }])
      setInput('')
    } else {
      setMessages((current) => current.filter((item) => item.role !== 'error'))
    }

    const taskId = crypto.randomUUID()
    const controller = new AbortController()
    abortRef.current = controller
    setIsSending(true)
    setAgentStatuses(idleStatuses)
    setHandoff(null)
    setReturningAgent(null)
    setIntakeActive(false)
    setFinalDeliveryActive(false)
    if (returnTimerRef.current !== null) {
      window.clearTimeout(returnTimerRef.current)
      returnTimerRef.current = null
    }
    setUploadSummary(files.length ? '正在整理项目上下文...' : null)
    let streamError: string | null = null

    try {
      const context = files.length ? await uploadProjectFiles(files) : null
      if (context) setUploadSummary(`${context.files.length} 个文件 · ${formatBytes(context.total_bytes)}`)
      await streamDebugTask({
        message,
        ...(context ? { context_id: context.context_id } : {}),
        run_tests: runTests,
        test_command: testCommand,
      }, (event) => {
        if (event.type === 'error') {
          streamError = event.message
          const failed = activeAgentRef.current
          if (failed) setAgentStatuses((current) => ({ ...current, [failed]: 'error' }))
          return
        }
        handleStreamEvent(taskId, event)
      }, controller.signal)
      if (streamError) throw new ApiError(streamError)
      setIsBackendOnline(true)
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        setMessages((current) => [...current, {
          id: crypto.randomUUID(), role: 'error', content: '任务已停止，已保留当前生成结果。', originalMessage: message,
        }])
      } else {
        const content = error instanceof Error ? error.message : '多智能体任务执行失败，请稍后重试。'
        setMessages((current) => [...current, {
          id: crypto.randomUUID(), role: 'error', content, originalMessage: message,
        }])
        if (error instanceof ApiError && error.isNetworkError) {
          setIsBackendOnline(false)
          setHealth(null)
        }
      }
    } finally {
      abortRef.current = null
      activeAgentRef.current = null
      setHandoff(null)
      setIntakeActive(false)
      setIsSending(false)
    }
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    void submitMessage(input)
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void submitMessage(input)
    }
  }

  const chooseFiles = (event: ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(event.target.files ?? [])
    setFiles((current) => {
      const known = new Set(current.map((file) => `${file.name}-${file.size}-${file.lastModified}`))
      return [...current, ...selected.filter((file) => !known.has(`${file.name}-${file.size}-${file.lastModified}`))]
    })
    event.target.value = ''
  }

  const resetConversation = () => {
    abortRef.current?.abort()
    setMessages(initialMessages)
    setInput('')
    setFiles([])
    setUploadSummary(null)
    setAgentStatuses(idleStatuses)
    setHandoff(null)
    setReturningAgent(null)
    setIntakeActive(false)
    setFinalDeliveryActive(false)
    if (returnTimerRef.current !== null) {
      window.clearTimeout(returnTimerRef.current)
      returnTimerRef.current = null
    }
  }

  const onAgentSaved = (config: AgentModelConfig) => {
    setConfigs((current) => ({ ...current, [config.agent_id]: config }))
    setHealth((current) => config.agent_id === 'bughunter' && current ? {
      ...current,
      provider: config.provider,
      provider_name: config.provider_name,
      model: config.model,
      model_configured: config.configured,
    } : current)
  }

  const statusLabel = isBackendOnline === null ? '正在连接' : isBackendOnline ? '服务在线' : '服务离线'
  const StatusIcon = isBackendOnline === null ? LoaderCircle : isBackendOnline ? Wifi : WifiOff
  const activeTitle = activeAgent ? `${agentMeta[activeAgent].name} 正在工作` : isSending ? '团队正在准备' : '多智能体任务台'
  const composerPlaceholder = isBackendOnline === false
    ? '后端服务离线，启动后即可发送任务'
    : !allAgentsConfigured
      ? '请先点击办公室机器人完成三位智能体的模型配置'
      : '描述问题、粘贴日志，或附加代码文件和 ZIP 项目...'

  const sidebarAgents = useMemo(() => agentOrder.map((id) => ({ id, ...agentMeta[id] })), [])

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-group">
          <button className="icon-button sidebar-toggle" type="button" aria-label="打开团队面板" onClick={() => setIsSidebarOpen((open) => !open)}>
            {isSidebarOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
          <div className="brand-logo-wrap" aria-hidden="true"><img src="/codebugger-cd-logo.svg" alt="" /></div>
          <div className="brand-copy"><strong>CoDebugger</strong><span>多智能体协作调试平台</span></div>
        </div>
        <div className="topbar-actions">
          <button className="model-settings-trigger" type="button" onClick={() => setSelectedAgent('bughunter')}>
            <Settings2 size={16} /><span>智能体模型</span><b>{configuredCount}/3</b>
          </button>
          <button type="button" className={`service-status ${isBackendOnline === false ? 'offline' : ''} ${isBackendOnline === null ? 'connecting' : ''}`} onClick={() => void refreshConnection()}>
            <StatusIcon className={isBackendOnline === null ? 'spin' : ''} size={15} /><span>{statusLabel}</span>
          </button>
        </div>
      </header>

      <div className="workspace">
        {isSidebarOpen && <button className="sidebar-backdrop" type="button" aria-label="关闭团队面板" onClick={() => setIsSidebarOpen(false)} />}
        <aside className={`sidebar ${isSidebarOpen ? 'open' : ''}`}>
          <div className="sidebar-topline"><div><span className="section-eyebrow">AGENT PIPELINE</span><h2>协作团队</h2></div><span className="agent-count">3</span></div>
          <div className="agent-list">
            {sidebarAgents.map(({ id, Icon, name, role }) => {
              const status = agentStatuses[id]
              const config = configs[id]
              return (
                <button className={`agent-item ${status}`} type="button" key={id} onClick={() => setSelectedAgent(id)}>
                  <span className={`agent-avatar ${id}`}><Icon size={18} /></span>
                  <span className="agent-copy"><strong>{name}</strong><span>{role}</span><small>{config?.configured ? `${config.provider_name} · ${config.model}` : '未配置模型'}</small></span>
                  <span className={`agent-presence ${status}`} />
                </button>
              )
            })}
          </div>
          <div className="pipeline-card">
            <div className="pipeline-heading"><Bot size={16} /><strong>任务链路</strong></div>
            {agentOrder.map((id, index) => (
              <div key={id} className="pipeline-row">
                <div className={`pipeline-step ${agentStatuses[id]}`}><span>0{index + 1}</span><div><strong>{agentMeta[id].name}</strong><small>{agentStatuses[id] === 'working' ? '执行中' : agentStatuses[id] === 'complete' ? '已完成' : '充电中'}</small></div>{agentStatuses[id] === 'complete' && <Check size={14} />}</div>
                {index < 2 && <div className="pipeline-line" />}
              </div>
            ))}
          </div>
          <div className="mode-note"><ShieldCheck size={17} /><div><strong>受控执行</strong><p>仅运行预设测试命令，子进程不会继承模型 API Key。</p></div></div>
        </aside>

        <main className="main-workbench">
          <div className="workbench-heading">
            <div><span>DEBUG SESSION</span><h1>{activeTitle}</h1><p>{health ? `${health.provider_name} 服务已连接` : '等待后端与模型服务'}</p></div>
            <button className="new-chat" type="button" onClick={resetConversation} disabled={isSending}><Plus size={17} /><span>新任务</span></button>
          </div>

          <AgentOffice
            statuses={agentStatuses}
            configs={configs}
            handoff={handoff}
            returningAgent={returningAgent}
            intakeActive={intakeActive}
            finalDeliveryActive={finalDeliveryActive}
            onConfigure={setSelectedAgent}
          />

          <section className="message-list" aria-live="polite" aria-label="多智能体执行报告">
            {isBackendOnline === false && (
              <div className="offline-banner"><WifiOff size={17} /><div><strong>后端服务未连接</strong><span>页面不会伪装在线，启动后端后再重新检测。</span></div><button type="button" onClick={() => void refreshConnection()}><RefreshCw size={15} />重新检测</button></div>
            )}
            {isBackendOnline === true && !allAgentsConfigured && (
              <div className="offline-banner configuration"><Settings2 size={17} /><div><strong>还有 {3 - configuredCount} 位智能体未配置</strong><span>点击上方机器人，分别选择模型服务并填写 API Key。</span></div><button type="button" onClick={() => setSelectedAgent(agentOrder.find((id) => !configs[id]?.configured) ?? 'bughunter')}>立即配置</button></div>
            )}
            <div className="message-stream">
              {messages.map((message) => {
                const Icon = message.agentId ? agentMeta[message.agentId].Icon : message.role === 'error' ? X : Bot
                return (
                  <article className={`message-row ${message.role} ${message.agentId ?? ''}`} key={message.id}>
                    {message.role !== 'user' && <div className={`message-avatar ${message.agentId ?? message.role}`}><Icon size={17} /></div>}
                    <div className="message-content">
                      {message.agentName && <div className="message-meta"><strong>{message.agentName}</strong><span>{message.agentId ? agentMeta[message.agentId].role : '协作中枢'}</span></div>}
                      <div className={`message-bubble ${message.content ? '' : 'streaming-empty'}`}>
                        {message.role === 'assistant' ? <MarkdownMessage content={message.content || '正在读取任务上下文...'} /> : <span>{message.content}</span>}
                        {message.role === 'error' && message.originalMessage && <button type="button" className="retry-button" onClick={() => void submitMessage(message.originalMessage!, false)}><RotateCcw size={14} />重新执行</button>}
                      </div>
                    </div>
                  </article>
                )
              })}
              <div ref={messageEndRef} />
            </div>
          </section>

          <div className="composer-wrap">
            {files.length > 0 && <div className="file-strip">{files.map((file, index) => <span className="file-chip" key={`${file.name}-${file.lastModified}`}><FileCode2 size={14} /><span><strong>{file.name}</strong><small>{formatBytes(file.size)}</small></span><button type="button" onClick={() => setFiles((current) => current.filter((_, itemIndex) => itemIndex !== index))} aria-label={`移除 ${file.name}`}><X size={13} /></button></span>)}{uploadSummary && <span className="context-summary"><Check size={13} />{uploadSummary}</span>}</div>}
            <div className="execution-controls">
              <label className="test-toggle"><input type="checkbox" checked={runTests} onChange={(event) => setRunTests(event.target.checked)} /><span /><strong>执行安全测试</strong></label>
              <select value={testCommand} onChange={(event) => setTestCommand(event.target.value as TestCommandId)} disabled={!runTests} aria-label="测试命令">{testCommands.map((item) => <option value={item.value} key={item.value}>{item.label}</option>)}</select>
              <span className="trust-note"><ShieldCheck size={13} />仅对可信项目启用</span>
            </div>
            <form className="composer" onSubmit={handleSubmit}>
              <textarea ref={textareaRef} value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={handleKeyDown} maxLength={5000} rows={1} placeholder={composerPlaceholder} aria-label="输入调试任务" />
              <div className="composer-actions">
                <div className="composer-tools"><input ref={fileInputRef} type="file" multiple accept=".zip,.py,.js,.jsx,.ts,.tsx,.vue,.java,.go,.rs,.c,.cpp,.cs,.html,.css,.json,.md,.sql,.yaml,.yml" onChange={chooseFiles} /><button type="button" className="attach-button" onClick={() => fileInputRef.current?.click()} title="附加代码或 ZIP"><Paperclip size={17} /><span>附加项目</span></button><span>{files.length ? `已选择 ${files.length} 个文件` : '源码或 ZIP，不限制文件数量'}</span></div>
                {isSending ? <button className="stop-button" type="button" onClick={() => abortRef.current?.abort()} aria-label="停止任务"><Square size={15} /><span>停止</span></button> : <button className="send-button" type="submit" disabled={!input.trim() || !allAgentsConfigured || isBackendOnline !== true} aria-label="开始多智能体任务"><ArrowUp size={19} /></button>}
              </div>
            </form>
          </div>
        </main>
      </div>

      {selectedAgent && (
        <ModelSettings open online={isBackendOnline === true} agentId={selectedAgent} agentName={agentMeta[selectedAgent].name} config={selectedConfig} onClose={() => setSelectedAgent(null)} onSaved={onAgentSaved} />
      )}
    </div>
  )
}

export default App
