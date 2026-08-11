import type { Dataset, ModelSettings, Run, RunDetail, StandardSummary, Suggestion } from './types'

const base = import.meta.env.VITE_API_BASE_URL || ''

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers)
  if (options?.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const response = await fetch(`${base}${path}`, { ...options, headers })
  if (!response.ok) {
    let message = `请求失败 (${response.status})`
    try {
      const payload = await response.json()
      message = payload.detail || message
    } catch { /* keep status message */ }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

export const api = {
  health: () => request<{ status: string; version: string; provider: string; api_key_configured: boolean }>('/api/health'),
  settings: () => request<{ models: ModelSettings; api_key_configured: boolean }>('/api/settings'),
  saveSettings: (models: ModelSettings) => request<{ models: ModelSettings; api_key_configured: boolean }>('/api/settings', { method: 'PUT', body: JSON.stringify(models) }),
  models: () => request<{ data: Array<{ id?: string; model?: string; owned_by?: string }> }>('/api/models'),
  demo: () => request<{ standard_markdown: string; dataset_csv: string; standard_template: string }>('/api/demo'),
  createDemoDataset: () => request<Dataset>('/api/demo/dataset', { method: 'POST' }),
  standards: () => request<StandardSummary[]>('/api/standards'),
  standard: (id: string) => request<StandardSummary>(`/api/standards/${id}`),
  compile: (name: string, source_markdown: string) => request<{ standard: StandardSummary; validation: { valid: boolean }; files: Record<string, string> }>('/api/standards/compile', { method: 'POST', body: JSON.stringify({ name, source_markdown }) }),
  activate: (id: string) => request<StandardSummary>(`/api/standards/${id}/activate`, { method: 'POST' }),
  revise: (id: string, payload: unknown) => request<{ standard: StandardSummary; affected_labels: string[] }>(`/api/standards/${id}/revise`, { method: 'POST', body: JSON.stringify(payload) }),
  datasets: () => request<Dataset[]>('/api/datasets'),
  datasetItems: (id: string) => request<Array<{ id: string; source_id?: string; text: string; gold_label?: string }>>(`/api/datasets/${id}/items`),
  uploadDataset: (file: File, name: string) => {
    const form = new FormData(); form.append('file', file); if (name) form.append('name', name)
    return request<Dataset>('/api/datasets', { method: 'POST', body: form })
  },
  runs: () => request<Run[]>('/api/runs'),
  createRun: (dataset_id: string, standard_id: string) => request<Run>('/api/runs', { method: 'POST', body: JSON.stringify({ dataset_id, standard_id }) }),
  retryRun: (id: string) => request<Run>(`/api/runs/${id}/retry`, { method: 'POST' }),
  run: (id: string) => request<RunDetail>(`/api/runs/${id}`),
  review: (id: string, human_label: string, note: string) => request(`/api/annotations/${id}/review`, { method: 'POST', body: JSON.stringify({ human_label, note }) }),
  mine: (id: string) => request<{ suggestions: Suggestion[] }>(`/api/runs/${id}/mine`, { method: 'POST' }),
  suggestions: (runId?: string) => request<Suggestion[]>(`/api/suggestions${runId ? `?run_id=${runId}` : ''}`),
  impactRun: (payload: unknown) => request<Run>('/api/impact-runs', { method: 'POST', body: JSON.stringify(payload) }),
  compare: (left: string, right: string) => request<{ left: { run: Run; metrics: import('./types').Metrics }; right: { run: Run; metrics: import('./types').Metrics } }>(`/api/compare?left_run_id=${left}&right_run_id=${right}`),
}
