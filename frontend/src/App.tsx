import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import type { LucideIcon } from 'lucide-react'
import {
  ArrowUp,
  Bug,
  Check,
  Code2,
  FlaskConical,
  Info,
  LoaderCircle,
  Menu,
  Plus,
  RefreshCw,
  RotateCcw,
  Settings2,
  Sparkles,
  Wifi,
  WifiOff,
  X,
} from 'lucide-react'
import {
  ApiError,
  checkHealth,
  getModelConfig,
  sendChatMessage,
  type HealthResponse,
  type ModelConfig,
} from './api'
import ModelSettings from './ModelSettings'
import './App.css'

type Message = {
  id: string
  role: 'user' | 'assistant' | 'error'
  content: string
  agentName?: string
  originalMessage?: string
}

type Agent = {
  name: string
  role: string
  status: string
  tone: 'cyan' | 'violet' | 'pink'
  active: boolean
  Icon: LucideIcon
}

const initialMessages: Message[] = [
  {
    id: 'welcome',
    role: 'assistant',
    agentName: 'BugHunter',
    content: '你好，我是你的 AI 调试搭档。把报错信息、关键代码或复现步骤发给我，我会帮你定位问题并给出清晰的修复建议。',
  },
]

const quickPrompts = [
  '帮我分析这段报错日志',
  '检查这段代码的潜在问题',
  '为这个问题设计排查步骤',
]

function App() {
  const [messages, setMessages] = useState<Message[]>(initialMessages)
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [isBackendOnline, setIsBackendOnline] = useState<boolean | null>(null)
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [modelConfig, setModelConfig] = useState<ModelConfig | null>(null)
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)
  const [isSettingsOpen, setIsSettingsOpen] = useState(false)
  const modelConfigLoadedRef = useRef(false)
  const messageEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const refreshConnection = useCallback(async () => {
    try {
      const nextHealth = await checkHealth()
      setHealth(nextHealth)
      setIsBackendOnline(true)
      if (!modelConfigLoadedRef.current) {
        try {
          setModelConfig(await getModelConfig())
          modelConfigLoadedRef.current = true
        } catch {
          // Health is authoritative for service availability; config can retry later.
        }
      }
    } catch {
      setHealth(null)
      setIsBackendOnline(false)
      modelConfigLoadedRef.current = false
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
    }
  }, [refreshConnection])

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isSending])

  useEffect(() => {
    const textarea = textareaRef.current
    if (!textarea) return
    textarea.style.height = 'auto'
    textarea.style.height = `${Math.min(textarea.scrollHeight, 144)}px`
  }, [input])

  const submitMessage = async (rawMessage: string, appendUser = true) => {
    const message = rawMessage.trim()
    if (!message || isSending) return
    if (isBackendOnline !== true) {
      setMessages((current) => [...current, {
        id: crypto.randomUUID(),
        role: 'error',
        content: '后端服务当前离线，请启动后端后重试。',
        originalMessage: message,
      }])
      return
    }
    if (!modelConfig?.configured) {
      setIsSettingsOpen(true)
      return
    }

    if (appendUser) {
      setMessages((current) => [
        ...current,
        { id: crypto.randomUUID(), role: 'user', content: message },
      ])
      setInput('')
    } else {
      setMessages((current) => current.filter((item) => item.role !== 'error'))
    }

    setIsSending(true)
    try {
      const response = await sendChatMessage(message)
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: response.reply,
          agentName: response.agent_name,
        },
      ])
      setIsBackendOnline(true)
    } catch (error) {
      const content = error instanceof Error ? error.message : '消息发送失败，请稍后重试。'
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: 'error',
          content,
          originalMessage: message,
        },
      ])
      if (error instanceof ApiError && error.isNetworkError) {
        setIsBackendOnline(false)
        setHealth(null)
      }
    } finally {
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

  const resetConversation = () => {
    setMessages(initialMessages)
    setInput('')
    textareaRef.current?.focus()
  }

  const handleConfigSaved = (config: ModelConfig) => {
    setModelConfig(config)
    modelConfigLoadedRef.current = true
    setHealth((current) => current ? {
      ...current,
      provider: config.provider,
      provider_name: config.provider_name,
      model: config.model,
      model_configured: config.configured,
    } : current)
  }

  const modelReady = isBackendOnline === true && Boolean(modelConfig?.configured)
  const agentTeam: Agent[] = [
    {
      name: 'BugHunter',
      role: '定位异常与根因',
      status: isBackendOnline === false ? '后端离线' : modelReady ? '模型已连接' : '等待模型配置',
      tone: 'cyan',
      active: modelReady,
      Icon: Bug,
    },
    { name: 'CodeAnalyst', role: '分析代码与依赖', status: '待接入', tone: 'violet', active: false, Icon: Code2 },
    { name: 'TestRunner', role: '生成并执行验证', status: '待接入', tone: 'pink', active: false, Icon: FlaskConical },
  ]

  const statusLabel = isBackendOnline === null ? '正在连接' : isBackendOnline ? '服务在线' : '服务离线'
  const StatusIcon = isBackendOnline === null ? LoaderCircle : isBackendOnline ? Wifi : WifiOff
  const modelLabel = modelConfig ? `${modelConfig.provider_name} · ${modelConfig.model}` : health?.model ?? '等待模型配置'
  const composerPlaceholder = isBackendOnline === false
    ? '后端服务离线，启动后即可发送消息'
    : !modelConfig?.configured
      ? '请先在模型设置中填写 API Key'
      : '描述问题、粘贴报错日志或关键代码...'

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-group">
          <button
            className="icon-button sidebar-toggle"
            type="button"
            aria-label={isSidebarOpen ? '关闭智能体列表' : '打开智能体列表'}
            aria-expanded={isSidebarOpen}
            onClick={() => setIsSidebarOpen((open) => !open)}
          >
            {isSidebarOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
          <div className="brand-logo-wrap" aria-hidden="true">
            <img src="/codebugger-cd-logo.svg" alt="" />
          </div>
          <div className="brand-copy">
            <strong>CoDebugger</strong>
            <span>多智能体调试工作台</span>
          </div>
        </div>

        <div className="topbar-actions">
          <button className="model-settings-trigger" type="button" aria-label="模型设置" onClick={() => setIsSettingsOpen(true)}>
            <Settings2 size={16} />
            <span>模型设置</span>
          </button>
          <button
            type="button"
            className={`service-status ${isBackendOnline === false ? 'offline' : ''} ${isBackendOnline === null ? 'connecting' : ''}`}
            onClick={() => void refreshConnection()}
            title="点击重新检测后端"
          >
            <StatusIcon size={15} aria-hidden="true" />
            <span>{statusLabel}</span>
          </button>
        </div>
      </header>

      <div className="workspace">
        {isSidebarOpen && (
          <button className="sidebar-backdrop" type="button" aria-label="关闭智能体列表" onClick={() => setIsSidebarOpen(false)} />
        )}

        <aside className={`sidebar ${isSidebarOpen ? 'open' : ''}`}>
          <div className="sidebar-topline">
            <div><span className="section-eyebrow">AGENT TEAM</span><h2>协作智能体</h2></div>
            <span className="agent-count">{agentTeam.length}</span>
          </div>

          <div className="agent-list">
            {agentTeam.map(({ Icon, ...agent }) => (
              <div className={`agent-item ${agent.active ? 'active' : ''}`} key={agent.name}>
                <div className={`agent-avatar ${agent.tone}`}><Icon size={18} strokeWidth={1.9} /></div>
                <div className="agent-copy">
                  <div className="agent-name-line"><strong>{agent.name}</strong>{agent.active && <Sparkles size={13} />}</div>
                  <span>{agent.role}</span>
                  <small className={agent.active ? 'ready' : ''}>{agent.status}</small>
                </div>
                <span className={`agent-presence ${agent.active ? 'ready' : ''}`} aria-hidden="true" />
              </div>
            ))}
          </div>

          <div className="pipeline-card">
            <div className="pipeline-heading"><Sparkles size={16} /><strong>当前执行链路</strong></div>
            <div className={`pipeline-step ${modelReady ? 'active' : ''}`}>
              <span>01</span><div><strong>理解问题</strong><small>{modelReady ? 'BugHunter 已就绪' : '等待服务连接'}</small></div>
              {modelReady && <Check size={14} />}
            </div>
            <div className="pipeline-line" />
            <div className="pipeline-step"><span>02</span><div><strong>代码审查</strong><small>等待后续接入</small></div></div>
            <div className="pipeline-line" />
            <div className="pipeline-step"><span>03</span><div><strong>验证修复</strong><small>等待后续接入</small></div></div>
          </div>

          <div className="mode-note">
            <Info size={17} />
            <div><strong>{modelConfig?.provider_name ?? '模型服务'}</strong><p>{modelConfig ? `当前使用 ${modelConfig.model}` : '请在模型设置中选择服务并填写密钥。'}</p></div>
          </div>
        </aside>

        <main className="chat-panel">
          <div className="chat-heading">
            <div className="chat-title-group">
              <div className="chat-agent-icon"><Bug size={20} /></div>
              <div>
                <div className="title-line"><h1>BugHunter</h1><span className="model-chip">{modelLabel}</span></div>
                <p>专注定位异常、梳理根因并给出可执行修复建议</p>
              </div>
            </div>
            <button className="new-chat" type="button" disabled={isSending} onClick={resetConversation}>
              <Plus size={17} /><span>新会话</span>
            </button>
          </div>

          <section className="message-list" aria-live="polite" aria-label="会话消息">
            {isBackendOnline === false && (
              <div className="offline-banner">
                <WifiOff size={17} />
                <div><strong>后端服务未连接</strong><span>前端会自动重试，也可以立即重新检测。</span></div>
                <button type="button" onClick={() => void refreshConnection()}><RefreshCw size={15} />重新检测</button>
              </div>
            )}
            {isBackendOnline === true && !modelConfig?.configured && (
              <div className="offline-banner configuration">
                <Settings2 size={17} />
                <div><strong>模型尚未配置</strong><span>选择 API 服务并填写你的 API Key 后即可开始。</span></div>
                <button type="button" onClick={() => setIsSettingsOpen(true)}>打开设置</button>
              </div>
            )}
            <div className="message-stream">
              <div className="conversation-date"><span>今天</span></div>
              {messages.map((message, messageIndex) => (
                <article className={`message-row ${message.role}`} key={message.id}>
                  {message.role !== 'user' && (
                    <div className={`message-avatar ${message.role}`} aria-hidden="true">
                      {message.role === 'error' ? <X size={18} /> : <Bug size={18} />}
                    </div>
                  )}
                  <div className="message-content">
                    {message.agentName && <div className="message-meta"><strong>{message.agentName}</strong>{messageIndex === 0 && <span>AI 调试助手</span>}</div>}
                    <div className="message-bubble">
                      {message.content.split('\n').map((line, index) => <span key={`${message.id}-${index}`}>{line || '\u00a0'}</span>)}
                      {message.role === 'error' && message.originalMessage && (
                        <button type="button" className="retry-button" onClick={() => void submitMessage(message.originalMessage!, false)}>
                          <RotateCcw size={14} />重新发送
                        </button>
                      )}
                    </div>
                    {messageIndex === 0 && messages.length === 1 && (
                      <div className="quick-prompts" aria-label="快捷问题">
                        {quickPrompts.map((prompt) => <button key={prompt} type="button" onClick={() => void submitMessage(prompt)}><Sparkles size={14} />{prompt}</button>)}
                      </div>
                    )}
                  </div>
                </article>
              ))}
              {isSending && (
                <article className="message-row assistant">
                  <div className="message-avatar" aria-hidden="true"><Bug size={18} /></div>
                  <div className="message-content">
                    <div className="message-meta"><strong>BugHunter</strong><span>正在分析</span></div>
                    <div className="message-bubble typing" aria-label="正在等待模型响应"><span /><span /><span /></div>
                  </div>
                </article>
              )}
              <div ref={messageEndRef} />
            </div>
          </section>

          <div className="composer-wrap">
            <form className="composer" onSubmit={handleSubmit}>
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={handleKeyDown}
                maxLength={5000}
                rows={1}
                placeholder={composerPlaceholder}
                aria-label="输入调试消息"
              />
              <div className="composer-actions">
                <span>{input.length > 0 ? `${input.length}/5000` : 'AI 可能会犯错，请核对重要信息'}</span>
                <button className="send-button" type="submit" disabled={!input.trim() || isSending || !modelReady} aria-label={isSending ? '正在发送' : '发送消息'} title="发送消息">
                  {isSending ? <LoaderCircle className="spin" size={19} /> : <ArrowUp size={19} />}
                </button>
              </div>
            </form>
            <p>Enter 发送 · Shift + Enter 换行</p>
          </div>
        </main>
      </div>

      {isSettingsOpen && (
        <ModelSettings
          open
          online={isBackendOnline === true}
          config={modelConfig}
          onClose={() => setIsSettingsOpen(false)}
          onSaved={handleConfigSaved}
        />
      )}
    </div>
  )
}

export default App
