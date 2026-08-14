import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import {
  Check,
  CircleCheck,
  Eye,
  EyeOff,
  KeyRound,
  LoaderCircle,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  TriangleAlert,
  X,
} from 'lucide-react'
import {
  ApiError,
  saveAgentModelConfig,
  testAgentModelConnection,
  type AgentId,
  type AgentModelConfig,
  type ProviderId,
  type ProviderOption,
} from './api'

type ModelSettingsProps = {
  open: boolean
  online: boolean
  agentId: AgentId
  agentName: string
  config: AgentModelConfig | null
  onClose: () => void
  onSaved: (config: AgentModelConfig) => void
}

const fallbackProviders: ProviderOption[] = [
  { id: 'aliyun', name: '阿里百炼', default_model: 'qwen-plus', accent: '#ff6a00', configured: false },
  { id: 'deepseek', name: 'DeepSeek', default_model: 'deepseek-v4-flash', accent: '#4d6bfe', configured: false },
  { id: 'minimax', name: 'MiniMax', default_model: 'MiniMax-M2.1', accent: '#e846a8', configured: false },
  { id: 'xiaomi', name: '小米 MiMo', default_model: 'mimo-v2-flash', accent: '#ff6900', configured: false },
  { id: 'kimi', name: 'Kimi', default_model: 'kimi-k2.5', accent: '#111827', configured: false },
  { id: 'zhipu', name: '智谱', default_model: 'glm-5', accent: '#345cff', configured: false },
]

const providerLogos: Record<ProviderId, string> = {
  aliyun: '/provider-logos/aliyun.svg',
  deepseek: '/provider-logos/deepseek.ico',
  minimax: '/provider-logos/minimax.png',
  xiaomi: '/provider-logos/xiaomi.png',
  kimi: '/provider-logos/kimi.ico',
  zhipu: '/provider-logos/zhipu.png',
}

function ModelSettings({ open, online, agentId, agentName, config, onClose, onSaved }: ModelSettingsProps) {
  const providers = config?.providers ?? fallbackProviders
  const [provider, setProvider] = useState<ProviderId>(config?.provider ?? 'deepseek')
  const [model, setModel] = useState(config?.model ?? 'deepseek-v4-flash')
  const [apiKey, setApiKey] = useState('')
  const [showApiKey, setShowApiKey] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [isTesting, setIsTesting] = useState(false)
  const [feedback, setFeedback] = useState<{ tone: 'success' | 'error'; text: string } | null>(null)
  const [testResult, setTestResult] = useState<{
    tone: 'success' | 'error'
    title: string
    message: string
  } | null>(null)

  const selectedProvider = useMemo(
    () => providers.find((item) => item.id === provider) ?? providers[0],
    [provider, providers],
  )
  const hasSavedKey = Boolean(selectedProvider?.configured)
  const hasUnsavedChanges = Boolean(
    config && (provider !== config.provider || model.trim() !== config.model || apiKey.trim()),
  )

  useEffect(() => {
    if (!open) return
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (testResult) {
        setTestResult(null)
      } else {
        onClose()
      }
    }
    window.addEventListener('keydown', handleEscape)
    return () => window.removeEventListener('keydown', handleEscape)
  }, [open, onClose, testResult])

  if (!open) return null

  const chooseProvider = (nextProvider: ProviderOption) => {
    setProvider(nextProvider.id)
    setModel(nextProvider.id === config?.provider ? config.model : nextProvider.default_model)
    setApiKey('')
    setFeedback(null)
  }

  const handleSave = async () => {
    if (!online) {
      setFeedback({ tone: 'error', text: '后端未启动，暂时无法保存配置。' })
      return
    }
    if (!model.trim()) {
      setFeedback({ tone: 'error', text: '请填写模型名称。' })
      return
    }
    if (!apiKey.trim() && !hasSavedKey) {
      setFeedback({ tone: 'error', text: `请填写 ${selectedProvider.name} API Key。` })
      return
    }

    setIsSaving(true)
    setFeedback(null)
    try {
      const saved = await saveAgentModelConfig(agentId, {
        provider,
        model: model.trim(),
        ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
      })
      onSaved(saved)
      setApiKey('')
      setFeedback({ tone: 'success', text: '配置已保存，密钥仅保留在后端内存中。' })
    } catch (error) {
      setFeedback({
        tone: 'error',
        text: error instanceof Error ? error.message : '保存失败，请稍后重试。',
      })
    } finally {
      setIsSaving(false)
    }
  }

  const handleTest = async () => {
    if (hasUnsavedChanges) {
      setTestResult({
        tone: 'error',
        title: '配置尚未保存',
        message: '请先保存当前供应商、模型或 API Key 修改，再执行连接测试。',
      })
      return
    }
    setIsTesting(true)
    setFeedback(null)
    try {
      const result = await testAgentModelConnection(agentId)
      setTestResult({
        tone: 'success',
        title: '模型连接成功',
        message: `${result.message}，当前配置可以正常用于对话。`,
      })
    } catch (error) {
      const message = error instanceof ApiError ? error.message : '模型连接测试失败。'
      setTestResult({
        tone: 'error',
        title: '模型连接失败',
        message,
      })
    } finally {
      setIsTesting(false)
    }
  }

  return (
    <div className="settings-layer" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose()
    }}>
      <section className="settings-dialog" role="dialog" aria-modal="true" aria-labelledby="model-settings-title">
        <header className="settings-header">
          <div className="settings-title-icon"><SlidersHorizontal size={20} /></div>
          <div>
            <span>MODEL SERVICE</span>
            <h2 id="model-settings-title">{agentName} 专属模型</h2>
          </div>
          <button className="icon-button settings-close" type="button" onClick={onClose} aria-label="关闭设置">
            <X size={20} />
          </button>
        </header>

        <div className="settings-body">
          {!online && (
            <div className="settings-offline">
              <Server size={17} />
              <span>后端服务离线。启动后端后才能保存和测试配置。</span>
            </div>
          )}

          <div className="setting-block">
            <div className="setting-label">
              <span>01</span>
              <div><strong>选择 API 服务</strong><small>仅用于 {agentName} 的工作阶段</small></div>
            </div>
            <div className="provider-grid">
              {providers.map((item) => (
                <button
                  type="button"
                  className={`provider-option ${provider === item.id ? 'selected' : ''}`}
                  key={item.id}
                  onClick={() => chooseProvider(item)}
                  style={{ '--provider-accent': item.accent } as CSSProperties}
                >
                  <span className="provider-mark"><img src={providerLogos[item.id]} alt="" /></span>
                  <span className="provider-copy"><strong>{item.name}</strong><small>{item.default_model}</small></span>
                  {item.configured && <span className="provider-ready" title="已保存密钥"><Check size={11} /></span>}
                </button>
              ))}
            </div>
          </div>

          <div className="setting-block compact">
            <div className="setting-label">
              <span>02</span>
              <div><strong>模型名称</strong><small>可按服务商支持情况调整</small></div>
            </div>
            <label className="settings-input-row">
              <Server size={17} />
              <input value={model} onChange={(event) => setModel(event.target.value)} maxLength={120} />
            </label>
            <div className="endpoint-line"><span>API Endpoint</span><code>{selectedProvider?.id === config?.provider ? config.base_url : '由服务商预设管理'}</code></div>
          </div>

          <div className="setting-block compact">
            <div className="setting-label">
              <span>03</span>
              <div><strong>API Key</strong><small>保存后不会再次返回明文</small></div>
            </div>
            <label className="settings-input-row secret-input">
              <KeyRound size={17} />
              <input
                type={showApiKey ? 'text' : 'password'}
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder={hasSavedKey ? '输入新密钥以替换当前密钥' : `输入 ${selectedProvider?.name ?? ''} API Key`}
                autoComplete="new-password"
                maxLength={512}
              />
              <button type="button" onClick={() => setShowApiKey((visible) => !visible)} aria-label={showApiKey ? '隐藏 API Key' : '显示 API Key'}>
                {showApiKey ? <EyeOff size={17} /> : <Eye size={17} />}
              </button>
            </label>
            {hasSavedKey && (
              <div className="masked-key"><ShieldCheck size={15} /><span>当前密钥</span><code>{provider === config?.provider ? config.api_key_masked : '已安全保存'}</code></div>
            )}
          </div>

          {feedback && <div className={`settings-feedback ${feedback.tone}`}>{feedback.tone === 'success' ? <Check size={16} /> : <X size={16} />}<span>{feedback.text}</span></div>}
        </div>

        <footer className="settings-footer">
          <div className="privacy-note"><ShieldCheck size={15} /><span>{agentName} 的密钥不会写入浏览器缓存或明文回显</span></div>
          <div className="settings-actions">
            <button className="test-button" type="button" disabled={!online || isTesting || isSaving || !config?.configured} onClick={() => void handleTest()}>
              {isTesting ? <LoaderCircle className="spin" size={16} /> : <Server size={16} />}
              测试连接
            </button>
            <button className="save-button" type="button" disabled={!online || isSaving || isTesting} onClick={() => void handleSave()}>
              {isSaving ? <LoaderCircle className="spin" size={16} /> : <Check size={16} />}
              保存配置
            </button>
          </div>
        </footer>
      </section>

      {testResult && (
        <div className="test-result-layer" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setTestResult(null)
        }}>
          <section
            className={`test-result-dialog ${testResult.tone}`}
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="test-result-title"
            aria-describedby="test-result-message"
          >
            <button className="icon-button result-close" type="button" onClick={() => setTestResult(null)} aria-label="关闭测试结果">
              <X size={19} />
            </button>
            <div className="result-icon" aria-hidden="true">
              {testResult.tone === 'success' ? <CircleCheck size={28} /> : <TriangleAlert size={28} />}
            </div>
            <span className="result-eyebrow">CONNECTION TEST</span>
            <h3 id="test-result-title">{testResult.title}</h3>
            <p id="test-result-message">{testResult.message}</p>
            <div className="result-model">
              <span className="result-provider-logo"><img src={providerLogos[provider]} alt="" /></span>
              <div><strong>{selectedProvider.name}</strong><small>{model}</small></div>
            </div>
            <button className="result-confirm" type="button" onClick={() => setTestResult(null)} autoFocus>
              返回模型设置
            </button>
          </section>
        </div>
      )}
    </div>
  )
}

export default ModelSettings
