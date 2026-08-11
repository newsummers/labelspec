export type Route = 'AUTO_ACCEPT' | 'REVIEW' | 'AMBIGUOUS' | 'SPEC_GAP'

export interface LabelItem { name: string; description: string }
export interface DefinitionRule {
  rule_id: string
  label: string
  definition: string
  include: string[]
  exclude: string[]
  positive_examples: string[]
  negative_examples: string[]
}
export interface BoundaryRule { rule_id: string; labels: string[]; condition: string; decision: string }
export interface PriorityRule { rule_id: string; principle: string }
export interface CompiledStandard {
  name: string
  labels: { labels: LabelItem[] }
  definition_rules: DefinitionRule[]
  decision_rules: { boundary_rules: BoundaryRule[]; priority_rules: PriorityRule[] }
}
export interface StandardSummary {
  id: string
  name: string
  version: number
  status: 'draft' | 'active' | 'archived'
  parent_id?: string
  created_at: string
  change_summary?: string
  counts: { labels: number; definitions: number; boundaries: number; priorities: number }
  compiled: CompiledStandard
  source_markdown?: string
  validation?: { valid: boolean; issues: Array<{ code: string; message: string }> }
  files?: Record<string, string>
  rule_stats?: Array<{ rule_id: string; type: string; labels: string[]; uses: number; conflicts: number; overrides: number; modifications: number }>
}
export interface Dataset {
  id: string
  name: string
  filename?: string
  item_count: number
  created_at: string
}
export interface DataItem {
  id: string
  source_id?: string
  text: string
  gold_label?: string
  metadata: Record<string, unknown>
}
export interface Run {
  id: string
  dataset_id: string
  dataset_name: string
  standard_id: string
  standard_name: string
  standard_version: number
  parent_run_id?: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  total: number
  processed: number
  error?: string
  created_at: string
}
export interface Metrics {
  total: number
  routes: Partial<Record<Route, number>>
  accuracy: number | null
  accuracy_sample_size: number
  auto_accept_rate: number
  review_rate: number
  rule_conflict_rate: number
}
export interface Annotation {
  id: string
  item_id: string
  text: string
  label?: string
  gold_label?: string
  human_label?: string
  review_note?: string
  candidates: string[]
  rules_used: string[]
  rule_reasons: Record<string, string>
  evidence: string
  confidence: number
  route: Route
  route_reasons: string[]
  disclosure: {
    definitions: DefinitionRule[]
    boundaries: BoundaryRule[]
    global_priority_rules: PriorityRule[]
    historical_cases: Array<Record<string, unknown>>
  }
  verifier: { verdict: string; explanation: string; confidence: number }
}
export interface RunDetail { run: Run; metrics: Metrics; annotations: Annotation[] }
export interface Suggestion {
  id: string
  run_id: string
  status: string
  case_ids: string[]
  payload: {
    title: string
    labels: string[]
    rules: string[]
    typical_cases: string[]
    problem: string
    target_rule_id?: string
    proposed_change: string
  }
}
export interface ModelSettings {
  compiler_model: string
  annotator_model: string
  verifier_model: string
  miner_model: string
  embedding_model: string
  auto_accept_threshold: number
  spec_gap_min_cluster_size: number
}
