export type Route = 'AUTO_ACCEPT' | 'REVIEW' | 'AMBIGUOUS' | 'SPEC_GAP'

export interface SourceReference { document_id: string; filename: string; locator: string }
export interface LabelItem {
  label_id: string
  name: string
  description: string
  parent_id?: string | null
  source_refs: SourceReference[]
}
export interface DefinitionRule {
  rule_id: string
  label_id: string
  definition: string
  include: string[]
  exclude: string[]
  source_refs: SourceReference[]
}
export interface BoundaryRule { rule_id: string; label_ids: string[]; scope_label_id?: string | null; condition: string; decision: string; source_refs: SourceReference[] }
export interface PriorityRule { rule_id: string; principle: string; scope_label_id?: string | null; source_refs: SourceReference[] }
export interface ConflictCandidate { rule_id?: string; label_ids: string[]; scope_label_id?: string | null; condition: string; decision: string; source_refs: SourceReference[] }
export interface CompilationConflict { conflict_id: string; kind: string; entity_key: string; message: string; source_refs: SourceReference[]; candidates?: ConflictCandidate[]; source_excerpts?: Array<{ filename: string; locator: string; excerpt: string }>; resolved: boolean }
export interface CompiledStandard {
  schema_version: '0.2'
  name: string
  labels: { labels: LabelItem[] }
  definition_rules: DefinitionRule[]
  decision_rules: { boundary_rules: BoundaryRule[]; priority_rules: PriorityRule[] }
  conflicts: CompilationConflict[]
}
export type DocumentRole = 'auto' | 'definition' | 'boundary' | 'priority'
export interface StandardSource { id: string; filename: string; media_type: string; sha256: string; metadata: Record<string, unknown>; created_at: string; role?: DocumentRole }
export interface StandardChange { id: string; operation: 'add' | 'update' | 'delete' | 'move'; entity_type: string; entity_id?: string; before?: unknown; after?: unknown; reason?: string; origin: string; created_at: string }
export interface StandardSummary {
  id: string
  name: string
  version: number
  status: 'draft' | 'active' | 'archived'
  parent_id?: string
  family_id: string
  created_at: string
  change_summary?: string
  counts: { labels: number; nodes?: number; definitions: number; boundaries: number; priorities: number }
  compiled: CompiledStandard
  source_markdown?: string
  validation?: { valid: boolean; issues: Array<{ code: string; message: string; path?: string; severity?: string }> }
  files?: Record<string, string>
  sources?: StandardSource[]
  changes?: StandardChange[]
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
