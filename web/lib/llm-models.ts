/**
 * Live LLM model fetcher — talks to provider /models endpoints from the browser.
 * Each helper returns a normalised list: { id, label, free, context }.
 */

export type LLMModel = {
  id: string
  label: string
  free: boolean
  context_length?: number
  pricing?: { prompt?: string; completion?: string } | null
}

export async function fetchOpenRouterModels(apiKey?: string): Promise<LLMModel[]> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (apiKey) headers['Authorization'] = `Bearer ${apiKey}`
  const r = await fetch('https://openrouter.ai/api/v1/models', { headers })
  if (!r.ok) throw new Error(`OpenRouter ${r.status}`)
  const data = await r.json()
  const list = (data.data || []) as Array<Record<string, unknown>>
  return list.map((m) => {
    const id = String(m.id || '')
    const pricing = (m.pricing || {}) as { prompt?: string; completion?: string }
    const free = id.endsWith(':free') ||
                 pricing.prompt === '0' || pricing.prompt === 0 as unknown as string
    return {
      id,
      label: String(m.name || id),
      free,
      context_length: typeof m.context_length === 'number' ? m.context_length : undefined,
      pricing,
    }
  })
}

export async function fetchAnthropicModels(apiKey: string): Promise<LLMModel[]> {
  // Anthropic /v1/models requires the key
  const r = await fetch('https://api.anthropic.com/v1/models', {
    headers: {
      'x-api-key': apiKey,
      'anthropic-version': '2023-06-01',
      'Content-Type': 'application/json',
    },
  })
  if (!r.ok) throw new Error(`Anthropic ${r.status}`)
  const data = await r.json()
  const list = (data.data || []) as Array<Record<string, unknown>>
  return list.map((m) => ({
    id: String(m.id),
    label: String(m.display_name || m.id),
    free: false,
  }))
}

export async function fetchOpenAIModels(apiKey: string): Promise<LLMModel[]> {
  const r = await fetch('https://api.openai.com/v1/models', {
    headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
  })
  if (!r.ok) throw new Error(`OpenAI ${r.status}`)
  const data = await r.json()
  const list = (data.data || []) as Array<Record<string, unknown>>
  return list
    .filter((m) => {
      const id = String(m.id || '')
      // Include only chat-capable models
      return id.startsWith('gpt-') || id.startsWith('o1') || id.startsWith('chatgpt')
    })
    .map((m) => ({
      id: String(m.id),
      label: String(m.id),
      free: false,
    }))
}

export async function fetchGroqModels(apiKey: string): Promise<LLMModel[]> {
  const r = await fetch('https://api.groq.com/openai/v1/models', {
    headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
  })
  if (!r.ok) throw new Error(`Groq ${r.status}`)
  const data = await r.json()
  const list = (data.data || []) as Array<Record<string, unknown>>
  return list.map((m) => ({
    id: String(m.id),
    label: String(m.id),
    free: true, // Groq has free tier with rate limits
    context_length: typeof m.context_window === 'number' ? m.context_window : undefined,
  }))
}

export async function fetchGeminiModels(apiKey: string): Promise<LLMModel[]> {
  const r = await fetch(`https://generativelanguage.googleapis.com/v1beta/models?key=${apiKey}`)
  if (!r.ok) throw new Error(`Gemini ${r.status}`)
  const data = await r.json()
  const list = (data.models || []) as Array<Record<string, unknown>>
  return list
    .filter((m) => {
      const methods = (m.supportedGenerationMethods || []) as string[]
      return methods.includes('generateContent')
    })
    .map((m) => ({
      id: String(m.name || '').replace('models/', ''),
      label: String(m.displayName || m.name),
      free: true,
    }))
}

export async function fetchOllamaModels(baseUrl = 'http://localhost:11434'): Promise<LLMModel[]> {
  const r = await fetch(`${baseUrl.replace(/\/$/, '')}/api/tags`)
  if (!r.ok) throw new Error(`Ollama ${r.status}`)
  const data = await r.json()
  const list = (data.models || []) as Array<Record<string, unknown>>
  return list.map((m) => ({
    id: String(m.name || m.model),
    label: String(m.name || m.model),
    free: true,
  }))
}

export async function fetchLMStudioModels(baseUrl = 'http://localhost:1234'): Promise<LLMModel[]> {
  const r = await fetch(`${baseUrl.replace(/\/$/, '')}/v1/models`)
  if (!r.ok) throw new Error(`LM Studio ${r.status}`)
  const data = await r.json()
  const list = (data.data || []) as Array<Record<string, unknown>>
  return list.map((m) => ({
    id: String(m.id),
    label: String(m.id),
    free: true,
  }))
}

export async function fetchModelsForProvider(
  provider: string,
  apiKey?: string,
  baseUrl?: string,
): Promise<LLMModel[]> {
  switch (provider) {
    case 'openrouter': return fetchOpenRouterModels(apiKey)
    case 'anthropic':  return apiKey ? fetchAnthropicModels(apiKey) : []
    case 'openai':     return apiKey ? fetchOpenAIModels(apiKey)    : []
    case 'groq':       return apiKey ? fetchGroqModels(apiKey)      : []
    case 'gemini':     return apiKey ? fetchGeminiModels(apiKey)    : []
    case 'ollama':     return fetchOllamaModels(baseUrl || 'http://localhost:11434')
    case 'lmstudio':   return fetchLMStudioModels(baseUrl || 'http://localhost:1234')
    default: return []
  }
}

export async function testProviderKey(
  provider: string,
  apiKey: string,
  baseUrl?: string,
): Promise<{ ok: boolean; message: string; modelsCount?: number }> {
  try {
    const models = await fetchModelsForProvider(provider, apiKey, baseUrl)
    return { ok: true, message: `OK — ${models.length} models available`, modelsCount: models.length }
  } catch (e) {
    return { ok: false, message: e instanceof Error ? e.message : String(e) }
  }
}
