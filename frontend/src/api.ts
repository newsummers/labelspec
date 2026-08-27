import type { Dataset, DocumentRole, ModelSettings, Run, RunDetail, StandardSummary, Suggestion } from './types'

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
  standardTemplateUrl: '/api/standards/template',
  createDemoDataset: () => request<Dataset>('/api/demo/dataset', { method: 'POST' }),
  standards: () => request<StandardSummary[]>('/api/standards'),
  standard: (id: string) => request<StandardSummary>(`/api/standards/${id}`),
  deleteStandard: (id: string) => request<{ id: string; name: string; version: number; deleted_source_documents: number; deleted_family: boolean }>(`/api/standards/${id}`, { method: 'DELETE' }),
  compile: (name: string, source_markdown: string) => request<{ standard: StandardSummary; validation: { valid: boolean }; files: Record<string, string> }>('/api/standards/compile', { method: 'POST', body: JSON.stringify({ name, source_markdown }) }),
  compileFiles: (name: string, files: File[], baseStandardId?: string, roles?: DocumentRole[]) => {
    const form = new FormData()
    form.append('name', name)
    files.forEach(file => form.append('files', file))
    roles?.forEach(role => form.append('roles', role))
    if (baseStandardId) form.append('base_standard_id', baseStandardId)
    return request<{ standard: StandardSummary; validation: { valid: boolean }; files: Record<string, string> }>('/api/standards/compile-files', { method: 'POST', body: form })
  },
  saveStandardVersion: (id: string, compiled: import('./types').CompiledStandard, reason: string, resolveConflicts = false) => request<{ standard: StandardSummary; validation: { valid: boolean }; files: Record<string, string> }>(`/api/standards/${id}/versions`, { method: 'POST', body: JSON.stringify({ compiled, reason, resolve_conflicts: resolveConflicts }) }),
  activate: (id: string) => request<StandardSummary>(`/api/standards/${id}/activate`, { method: 'POST' }),
  revise: (id: string, payload: unknown) => request<{ standard: StandardSummary; affected_labels: string[] }>(`/api/standards/${id}/revise`, { method: 'POST', body: JSON.stringify(payload) }),
  datasets: () => request<Dataset[]>('/api/datasets'),
  datasetItems: (id: string) => request<Array<{ id: string; source_id?: string; text: string; gold_label?: string }>>(`/api/datasets/${id}/items`),
  deleteDataset: (id: string) => request<{ id: string; name: string; filename?: string; deleted_items: number }>(`/api/datasets/${id}`, { method: 'DELETE' }),
  datasetTemplate: async () => {
    const response = await fetch(`${base}/api/datasets/template`)
    if (!response.ok) throw new Error('获取数据模板失败')
    return response.text()
  },
  uploadDataset: (file: File, name: string) => {
    const form = new FormData(); form.append('file', file); if (name) form.append('name', name)
    return request<Dataset>('/api/datasets', { method: 'POST', body: form })
  },
  runs: () => request<Run[]>('/api/runs'),
  createRun: (dataset_id: string, standard_id: string, concurrency = 1, trace_replicas = 3) => request<Run>('/api/runs', { method: 'POST', body: JSON.stringify({ dataset_id, standard_id, concurrency, trace_replicas }) }),
  retryRun: (id: string) => request<Run>(`/api/runs/${id}/retry`, { method: 'POST' }),
  pauseRun: (id: string) => request<Run>(`/api/runs/${id}/pause`, { method: 'POST' }),
  run: (id: string) => request<RunDetail>(`/api/runs/${id}`),
  review: (id: string, human_label: string, note: string) => request(`/api/annotations/${id}/review`, { method: 'POST', body: JSON.stringify({ human_label, note }) }),
  mine: (id: string) => request<{ suggestions: Suggestion[] }>(`/api/runs/${id}/mine`, { method: 'POST' }),
  suggestions: (runId?: string) => request<Suggestion[]>(`/api/suggestions${runId ? `?run_id=${runId}` : ''}`),
  rulePatches: (standardId?: string) => request<Array<Record<string, unknown>>>(`/api/rule-patches${standardId ? `?standard_id=${standardId}` : ''}`),
  updateRulePatch: (id: string, status?: string, payload?: Record<string, unknown>) => request<Record<string, unknown>>(`/api/rule-patches/${id}${status ? `?status=${encodeURIComponent(status)}` : ''}`, { method: 'PATCH', body: payload ? JSON.stringify({ payload }) : undefined }),
  applyRulePatch: (id: string) => request<Record<string, unknown>>(`/api/rule-patches/${id}/apply`, { method: 'POST' }),
  impactRun: (payload: unknown) => request<Run>('/api/impact-runs', { method: 'POST', body: JSON.stringify(payload) }),
  compare: (left: string, right: string) => request<{ left: { run: Run; metrics: import('./types').Metrics }; right: { run: Run; metrics: import('./types').Metrics } }>(`/api/compare?left_run_id=${left}&right_run_id=${right}`),
}
