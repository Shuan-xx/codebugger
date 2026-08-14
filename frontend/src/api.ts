const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
const CHAT_TIMEOUT_MS = 75_000
const REQUEST_TIMEOUT_MS = 6_000

export type ProviderId = 'aliyun' | 'deepseek' | 'minimax' | 'xiaomi' | 'kimi' | 'zhipu'
export type AgentId = 'bughunter' | 'codeanalyst' | 'testrunner'
export type TestCommandId = 'auto' | 'python-compile' | 'python-pytest' | 'npm-lint' | 'npm-test' | 'npm-build'

export type ProviderOption = {
  id: ProviderId
  name: string
  default_model: string
  accent: string
  configured: boolean
}

export type ModelConfig = {
  provider: ProviderId
  provider_name: string
  model: string
  base_url: string
  configured: boolean
  api_key_masked: string | null
  providers: ProviderOption[]
}

export type AgentModelConfig = ModelConfig & {
  agent_id: AgentId
  agent_name: string
}

export type HealthResponse = {
  status: 'ok'
  service: 'codebugger-backend'
  time: string
  provider: ProviderId
  provider_name: string
  model: string
  model_configured: boolean
}

export type ProjectContextResponse = {
  context_id: string
  files: Array<{ path: string; size: number; language: string }>
  total_bytes: number
  expires_in_seconds: number
}

export type TestExecutionEvent = {
  type: 'test_result'
  command_id: string
  command: string
  status: 'passed' | 'failed' | 'timeout' | 'skipped'
  exit_code: number | null
  duration_ms: number
  output: string
  truncated: boolean
}

export type StreamEvent =
  | { type: 'task_started'; agent_count: number; context_files: number }
  | { type: 'agent_status'; agent: AgentId; agent_name: string; role: string; status: 'working'; stage: number }
  | { type: 'token'; agent: AgentId; agent_name: string; content: string }
  | { type: 'agent_complete'; agent: AgentId; agent_name: string; content: string; stage: number }
  | { type: 'handoff'; from_agent: AgentId; from_name: string; to_agent: AgentId; to_name: string; message: string }
  | { type: 'final_delivery'; agent: 'testrunner'; agent_name: string; message: string }
  | TestExecutionEvent
  | { type: 'done'; status: 'completed'; reply: string; agents: AgentId[] }
  | { type: 'error'; status_code: number; message: string }

type ChatResponse = {
  reply: string
  agent_name: string
  status: string
}

export class ApiError extends Error {
  readonly isNetworkError: boolean

  constructor(message: string, isNetworkError = false) {
    super(message)
    this.name = 'ApiError'
    this.isNetworkError = isNetworkError
  }
}

const readErrorMessage = async (response: Response) => {
  try {
    const body = (await response.json()) as { detail?: string | Array<{ msg?: string }> }
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail)) {
      return body.detail.map((item) => item.msg).filter(Boolean).join('；')
    }
  } catch {
    // Use the status fallback when a proxy or upstream service returns non-JSON.
  }
  return `请求失败（${response.status}）`
}

const fetchWithTimeout = async (
  path: string,
  options: RequestInit = {},
  timeoutMs = REQUEST_TIMEOUT_MS,
) => {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      cache: 'no-store',
      signal: controller.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError('请求超时，请确认后端服务状态。', true)
    }
    throw new ApiError('无法连接后端服务，请确认后端已经启动。', true)
  } finally {
    window.clearTimeout(timeout)
  }
}

const parseJson = async <T>(response: Response): Promise<T> => {
  if (!response.ok) throw new ApiError(await readErrorMessage(response))
  try {
    return (await response.json()) as T
  } catch {
    throw new ApiError('后端返回了无法解析的响应。')
  }
}

export const checkHealth = async (): Promise<HealthResponse> => {
  const response = await fetchWithTimeout('/api/health')
  const body = await parseJson<HealthResponse>(response)
  if (body.status !== 'ok' || body.service !== 'codebugger-backend') {
    throw new ApiError('收到的不是 CoDebugger 后端响应。', true)
  }
  return body
}

export const getModelConfig = async (): Promise<ModelConfig> => {
  const response = await fetchWithTimeout('/api/model-config')
  return parseJson<ModelConfig>(response)
}

export const getAgentModelConfigs = async (): Promise<AgentModelConfig[]> => {
  const response = await fetchWithTimeout('/api/agents/model-config')
  return parseJson<AgentModelConfig[]>(response)
}

export const saveModelConfig = async (input: {
  provider: ProviderId
  model: string
  api_key?: string
}): Promise<ModelConfig> => {
  const response = await fetchWithTimeout('/api/model-config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  return parseJson<ModelConfig>(response)
}

export const saveAgentModelConfig = async (
  agentId: AgentId,
  input: { provider: ProviderId; model: string; api_key?: string },
): Promise<AgentModelConfig> => {
  const response = await fetchWithTimeout(`/api/agents/${agentId}/model-config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  return parseJson<AgentModelConfig>(response)
}

export const testModelConnection = async (): Promise<{ status: string; message: string }> => {
  const response = await fetchWithTimeout('/api/model-config/test', { method: 'POST' }, CHAT_TIMEOUT_MS)
  return parseJson(response)
}

export const testAgentModelConnection = async (
  agentId: AgentId,
): Promise<{ status: string; message: string }> => {
  const response = await fetchWithTimeout(
    `/api/agents/${agentId}/model-config/test`,
    { method: 'POST' },
    CHAT_TIMEOUT_MS,
  )
  return parseJson(response)
}

export const uploadProjectFiles = async (files: File[]): Promise<ProjectContextResponse> => {
  const form = new FormData()
  files.forEach((file) => form.append('files', file, file.webkitRelativePath || file.name))
  const response = await fetchWithTimeout('/api/context', { method: 'POST', body: form }, CHAT_TIMEOUT_MS)
  return parseJson<ProjectContextResponse>(response)
}

export const streamDebugTask = async (
  payload: {
    message: string
    context_id?: string
    run_tests: boolean
    test_command: TestCommandId
  },
  onEvent: (event: StreamEvent) => void,
  signal: AbortSignal,
): Promise<void> => {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/api/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      cache: 'no-store',
      signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError('无法连接后端服务，请确认后端已经启动。', true)
  }
  if (!response.ok) throw new ApiError(await readErrorMessage(response))
  if (!response.body) throw new ApiError('浏览器无法读取模型流式响应。')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const consume = (block: string) => {
    const data = block
      .split(/\r?\n/)
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trimStart())
      .join('\n')
    if (!data) return
    try {
      onEvent(JSON.parse(data) as StreamEvent)
    } catch {
      throw new ApiError('后端返回了无法解析的流式事件。')
    }
  }

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const blocks = buffer.split(/\r?\n\r?\n/)
    buffer = blocks.pop() ?? ''
    blocks.forEach(consume)
    if (done) break
  }
  if (buffer.trim()) consume(buffer)
}

const parseChatResponse = async (response: Response): Promise<ChatResponse> => {
  const body = await parseJson<ChatResponse>(response)
  if (typeof body.reply !== 'string' || typeof body.agent_name !== 'string' || typeof body.status !== 'string') {
    throw new ApiError('后端返回的数据格式不正确。')
  }
  if (body.status !== 'completed') throw new ApiError('模型任务未能完成，请稍后重试。')
  return body
}

export const sendChatMessage = async (message: string): Promise<ChatResponse> => {
  const response = await fetchWithTimeout(
    '/api/chat',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    },
    CHAT_TIMEOUT_MS,
  )
  return parseChatResponse(response)
}
