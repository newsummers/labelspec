import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  AlertTriangle, ArrowRight, BarChart3, Check, ChevronRight, CircleGauge, Database,
  FileCode2, FileDown, FlaskConical, GitBranch, GitCompareArrows, Layers3, Lightbulb, LoaderCircle,
  Pencil, Trash2,
  Play, Plus, RefreshCw, Save, ScanSearch, Settings, ShieldCheck, Sparkles,
  Upload, X,
} from 'lucide-react'
import { api } from './api'
import type {
  Annotation, CompiledStandard, Dataset, DocumentRole, Metrics, ModelCall, ModelSettings, Route, Run, RunDetail, StandardSummary, TraceEvent,
  Suggestion,
} from './types'

type Page = 'dashboard' | 'standards' | 'datasets' | 'runs' | 'gaps' | 'settings'

const nav: Array<{ id: Page; label: string; icon: typeof BarChart3 }> = [
  { id: 'dashboard', label: '总览', icon: BarChart3 },
  { id: 'standards', label: '标准', icon: FileCode2 },
  { id: 'datasets', label: '数据', icon: Database },
  { id: 'runs', label: '标注运行', icon: ScanSearch },
  { id: 'gaps', label: '规则改进', icon: Lightbulb },
  { id: 'settings', label: '模型设置', icon: Settings },
]

function date(value?: string) {
  if (!value) return '-'
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}
function pct(value?: number | null) { return value == null ? '-' : `${(value * 100).toFixed(1)}%` }
function ms(value?: number | null) { return value == null ? '-' : value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(1)} s` }
function Badge({ value, className = '' }: { value: string; className?: string }) { return <span className={`badge ${value} ${className}`.trim()}>{value}</span> }
const routeReasonLabels: Record<string, string> = {
  AMBIGUOUS: '意图模糊',
  'AMBIGUOUS FUTURE EVENT': '未来事件意图模糊',
  SPEC_GAP: '标准覆盖不足',
  NEEDS_CONTEXT: '需要上下文',
  LOW_CONFIDENCE: '置信度低',
  INVALID_ANNOTATOR_OUTPUT: '标注模型输出无效',
  INVALID_RULE_REFERENCE: '引用了无效规则',
  INVALID_LABEL: '标签无效',
  ANNOTATOR_REVIEW: '需要人工审核',
  MANUAL_REVIEW: '人工审核',
  AUTO_ACCEPT: '自动通过',
  OTHER: '其他原因',
}
const routeReasonWords: Record<string, string> = {
  ambiguous: '意图模糊',
  ambiguity: '存在歧义',
  future: '未来',
  event: '事件',
  events: '事件',
  intent: '意图',
  candidate: '候选',
  candidates: '候选',
  overlap: '交叉',
  overlapping: '交叉',
  conflict: '冲突',
  conflicts: '冲突',
  context: '上下文',
  confidence: '置信度',
  low: '低',
  high: '高',
  insufficient: '不足',
  unclear: '不明确',
  invalid: '无效',
  unsupported: '不支持',
  missing: '缺失',
  annotator: '标注模型',
  output: '输出',
  rule: '规则',
  rules: '规则',
  reference: '引用',
  label: '标签',
  labels: '标签',
  manual: '人工',
  review: '审核',
  needs: '需要',
  require: '需要',
  required: '必需',
  specification: '标准',
  spec: '标准',
  gap: '缺口',
  auto: '自动',
  accept: '通过',
}
function routeReasonKey(reason: Annotation['route_reasons'][number]) {
  const code = (reason.code || reason.message).trim()
  const normalized = code.replace(/[-_]+/g, ' ').replace(/\s+/g, ' ').toUpperCase()
  const label = routeReasonLabels[code] || routeReasonLabels[normalized] || localizeRouteReason(code)
  return `${reason.source}_${label}`
}
function localizeRouteReason(value: string) {
  if (/[\u4e00-\u9fff]/.test(value) && !/[a-z]/i.test(value)) return value
  const words = value.toLowerCase().replace(/[-_]+/g, ' ').split(/\s+/).filter(Boolean)
  const translated = words.map(word => /[\u4e00-\u9fff]/.test(word) ? word : routeReasonWords[word]).filter(Boolean)
  return translated.length ? translated.join('') : '其他原因'
}
function Spinner() { return <span className="spinner" /> }
function Empty({ icon: Icon = Layers3, title, text }: { icon?: typeof Layers3; title: string; text?: string }) {
  return <div className="empty"><div><Icon size={24} /><div className="empty-title">{title}</div>{text && <div className="empty-text">{text}</div>}</div></div>
}
function PageHead({ title, meta, children }: { title: string; meta?: string; children?: ReactNode }) {
  return <div className="page-head"><div><h1>{title}</h1>{meta && <p>{meta}</p>}</div>{children && <div className="actions">{children}</div>}</div>
}
function Modal({ title, children, footer, onClose, wide = false }: { title: string; children: ReactNode; footer?: ReactNode; onClose: () => void; wide?: boolean }) {
  return <div className="modal-backdrop" onMouseDown={onClose}><div className={`modal ${wide ? 'wide' : ''}`} onMouseDown={event => event.stopPropagation()}>
    <div className="modal-head"><h2>{title}</h2><button className="btn icon ghost" onClick={onClose} title="关闭"><X size={17} /></button></div>
    <div className="modal-body">{children}</div>{footer && <div className="modal-foot">{footer}</div>}
  </div></div>
}

export default function App() {
  const [page, setPage] = useState<Page>('dashboard')
  const [health, setHealth] = useState<{ version: string; api_key_configured: boolean } | null>(null)
  const [standards, setStandards] = useState<StandardSummary[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [runs, setRuns] = useState<Run[]>([])
  const [toast, setToast] = useState<{ text: string; error?: boolean } | null>(null)
  const [loading, setLoading] = useState(true)

  const notify = useCallback((text: string, error = false) => {
    setToast({ text, error }); window.setTimeout(() => setToast(null), 4200)
  }, [])
  const refresh = useCallback(async () => {
    try {
      const [healthData, standardData, datasetData, runData] = await Promise.all([
        api.health(), api.standards(), api.datasets(), api.runs(),
      ])
      setHealth(healthData); setStandards(standardData); setDatasets(datasetData); setRuns(runData)
    } catch (error) { notify(error instanceof Error ? error.message : '加载失败', true) }
    finally { setLoading(false) }
  }, [notify])

  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => {
    if (!runs.some(run => run.status === 'running' || run.status === 'queued')) return
    const timer = window.setInterval(() => { void refresh() }, 2500)
    return () => window.clearInterval(timer)
  }, [runs, refresh])

  const current = nav.find(item => item.id === page)!
  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark"><Layers3 size={17} /></span><span>LabelSpec</span><span className="version">v0.2</span></div>
      <nav className="nav">{nav.map(item => <button key={item.id} className={`nav-button ${page === item.id ? 'active' : ''}`} onClick={() => setPage(item.id)} title={item.label}><item.icon size={17} /><span>{item.label}</span></button>)}</nav>
      <div className="nav-footer"><div className="provider-state"><span className={`state-dot ${health?.api_key_configured ? 'ok' : ''}`} /><span>{health?.api_key_configured ? '千帆 Key 已配置' : 'API Key 未配置'}</span></div><span>Apache-2.0</span></div>
    </aside>
    <main className="main">
      <header className="topbar"><div className="top-title">{current.label}</div><div className="top-actions"><button className="btn icon ghost" onClick={() => void refresh()} title="刷新"><RefreshCw size={16} /></button>{health && <Badge value={health.api_key_configured ? 'API KEY SET' : 'API KEY REQUIRED'} />}</div></header>
      <section className="content">
        {loading ? <Empty icon={LoaderCircle} title="正在加载" /> : <>
          {page === 'dashboard' && <Dashboard standards={standards} datasets={datasets} runs={runs} setPage={setPage} />}
          {page === 'standards' && <StandardsPage standards={standards} refresh={refresh} notify={notify} />}
          {page === 'datasets' && <DatasetsPage datasets={datasets} standards={standards} refresh={refresh} notify={notify} setPage={setPage} />}
          {page === 'runs' && <RunsPage runs={runs} standards={standards} refresh={refresh} notify={notify} />}
          {page === 'gaps' && <GapsPage runs={runs} refresh={refresh} notify={notify} />}
          {page === 'settings' && <SettingsPage health={health} refresh={refresh} notify={notify} />}
        </>}
      </section>
    </main>
    {toast && <div className={`toast ${toast.error ? 'error' : ''}`}>{toast.text}</div>}
  </div>
}

function Dashboard({ standards, datasets, runs, setPage }: { standards: StandardSummary[]; datasets: Dataset[]; runs: Run[]; setPage: (page: Page) => void }) {
  const active = standards.find(item => item.status === 'active')
  const latest = runs.find(item => item.status === 'completed')
  const latestRunId = latest?.id
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  useEffect(() => { if (latestRunId) void api.run(latestRunId).then(value => setMetrics(value.metrics)).catch(() => setMetrics(null)) }, [latestRunId])
  return <div className="stack">
    <PageHead title="LabelSpec 工作台" meta={active ? `${active.name} · Standard v${active.version}` : '尚未激活业务标准'}>
      <button className="btn primary" onClick={() => setPage(active ? 'datasets' : 'standards')}><Plus size={15} />{active ? '开始标注' : '编译标准'}</button>
    </PageHead>
    <div className="four-col">
      <div className="metric"><div className="metric-label"><ShieldCheck size={14} />自动通过率</div><div className="metric-value">{pct(metrics?.auto_accept_rate)}</div><div className="metric-foot">最近完成运行</div></div>
      <div className="metric"><div className="metric-label"><CircleGauge size={14} />准确率</div><div className="metric-value">{pct(metrics?.accuracy)}</div><div className="metric-foot">{metrics?.accuracy_sample_size || 0} 条人工真值</div></div>
      <div className="metric"><div className="metric-label"><AlertTriangle size={14} />人工审核率</div><div className="metric-value">{pct(metrics?.review_rate)}</div><div className="metric-foot">REVIEW 路由</div></div>
      <div className="metric"><div className="metric-label"><GitCompareArrows size={14} />待确认反馈</div><div className="metric-value">{metrics?.routes.REVIEW || 0}</div><div className="metric-foot">REVIEW 条目</div></div>
    </div>
    <div className="flow">
      {[
        ['01', 'Standard', active ? `v${active.version} · ${active.counts.labels} Labels` : '未激活'],
        ['02', 'Data', `${datasets.reduce((sum, item) => sum + item.item_count, 0)} Cases`],
        ['03', 'Model', runs[0] ? `${runs[0].processed}/${runs[0].total}` : '未运行'],
        ['04', 'Review', `${metrics?.routes.REVIEW || 0} Cases`],
        ['05', 'Standard', standards.length > 1 ? `${standards.length} Versions` : '等待进化'],
      ].map(step => <div className="flow-step" key={step[0]}><div className="flow-number">{step[0]}</div><div className="flow-title">{step[1]}</div><div className="flow-meta">{step[2]}</div></div>)}
    </div>
    <div className="two-col">
      <div className="panel"><div className="panel-head"><h2>标准版本</h2><button className="btn ghost" onClick={() => setPage('standards')}>查看全部 <ChevronRight size={14} /></button></div>{standards.length ? <div className="list">{standards.slice(0, 4).map(item => <div className="list-item" key={item.id}><div className="list-title">{item.name} v{item.version}</div><div className="list-meta"><Badge value={item.status} /><span>{item.counts.definitions + item.counts.boundaries + item.counts.priorities} Rules</span><span>{date(item.created_at)}</span></div></div>)}</div> : <Empty title="暂无标准" />}</div>
      <div className="panel"><div className="panel-head"><h2>最近运行</h2><button className="btn ghost" onClick={() => setPage('runs')}>查看全部 <ChevronRight size={14} /></button></div>{runs.length ? <div className="list">{runs.slice(0, 4).map(item => <div className="list-item" key={item.id}><div className="list-title">{item.dataset_name}</div><div className="list-meta"><Badge value={item.status} /><span>Standard v{item.standard_version}</span><span>{item.processed}/{item.total}</span></div></div>)}</div> : <Empty title="暂无运行" />}</div>
    </div>
  </div>
}

function copyStandard(value: CompiledStandard): CompiledStandard {
  return JSON.parse(JSON.stringify(value)) as CompiledStandard
}

function nodePath(compiled: CompiledStandard, labelId: string): string {
  const byId = new Map(compiled.labels.labels.map(label => [label.label_id, label]))
  const parts: string[] = []
  const seen = new Set<string>()
  let current = byId.get(labelId)
  while (current && !seen.has(current.label_id)) {
    seen.add(current.label_id)
    parts.unshift(current.name)
    current = current.parent_id ? byId.get(current.parent_id) : undefined
  }
  return parts.join('/')
}

function nextCode(values: string[], prefix: string) {
  const max = values.reduce((value, item) => item.startsWith(prefix) ? Math.max(value, Number(item.slice(1)) || 0) : value, 0)
  return `${prefix}${String(max + 1).padStart(3, '0')}`
}

function inferRole(filename: string): DocumentRole {
  const value = filename.toLowerCase()
  if (['混淆', '边界', 'confusion', 'boundary'].some(token => value.includes(token))) return 'boundary'
  if (['优先级', 'priority'].some(token => value.includes(token))) return 'priority'
  if (['分类标准', '标签定义', 'taxonomy', 'definition'].some(token => value.includes(token))) return 'definition'
  return 'auto'
}

function StandardsPage({ standards, refresh, notify }: { standards: StandardSummary[]; refresh: () => Promise<void>; notify: (text: string, error?: boolean) => void }) {
  const [selectedId, setSelectedId] = useState(standards[0]?.id || '')
  const [detail, setDetail] = useState<StandardSummary | null>(null)
  const [tab, setTab] = useState<'taxonomy' | 'decisions' | 'sources' | 'history' | 'yaml'>('taxonomy')
  const [uploadOpen, setUploadOpen] = useState(false)
  const [uploadName, setUploadName] = useState('')
  const [uploadBase, setUploadBase] = useState<string | undefined>()
  const [files, setFiles] = useState<File[]>([])
  const [fileRoles, setFileRoles] = useState<DocumentRole[]>([])
  const [editor, setEditor] = useState<CompiledStandard | null>(null)
  const [reason, setReason] = useState('')
  const [conflictResolutions, setConflictResolutions] = useState<Record<string, { condition: string; decision: string }>>({})
  const [busy, setBusy] = useState(false)

  const load = useCallback(async (id: string) => { if (id) setDetail(await api.standard(id)) }, [])
  useEffect(() => { if (!selectedId && standards[0]) setSelectedId(standards[0].id) }, [standards, selectedId])
  useEffect(() => { void load(selectedId) }, [selectedId, load])

  const openUpload = (base?: StandardSummary) => {
    setUploadName(base?.name || '')
    setUploadBase(base?.id)
    setFiles([])
    setFileRoles([])
    setUploadOpen(true)
  }
  const runCompile = async () => {
    if (!uploadName.trim() || !files.length) return notify('请选择标准文档并填写名称', true)
    setBusy(true)
    try {
      const result = await api.compileFiles(uploadName.trim(), files, uploadBase, fileRoles)
      setUploadOpen(false)
      setSelectedId(result.standard.id)
      await refresh()
      await load(result.standard.id)
      notify(result.validation.valid ? `已创建 v${result.standard.version}` : `已创建 v${result.standard.version}，需要处理校验问题`)
    } catch (error) { notify(error instanceof Error ? error.message : '编译失败', true) } finally { setBusy(false) }
  }
  const activate = async () => {
    if (!detail) return
    setBusy(true)
    try { await api.activate(detail.id); await refresh(); await load(detail.id); notify('版本已激活') } catch (error) { notify(String(error), true) } finally { setBusy(false) }
  }
  const deleteSelected = async () => {
    if (!detail || detail.status === 'active') return
    const confirmed = window.confirm(
      `确定删除「${detail.name} v${detail.version}」吗？\n\n删除后不可恢复，且该版本的变更记录与来源关联也会被清理。`
    )
    if (!confirmed) return
    setBusy(true)
    try {
      const deleted = await api.deleteStandard(detail.id)
      const remaining = standards.filter(item => item.id !== deleted.id)
      setDetail(null)
      setSelectedId(remaining[0]?.id || '')
      await refresh()
      notify(`已删除 ${deleted.name} v${deleted.version}`)
    } catch (error) {
      notify(error instanceof Error ? error.message : '删除标准失败', true)
    } finally { setBusy(false) }
  }
  const changeEditor = (mutate: (value: CompiledStandard) => void) => {
    setEditor(current => { if (!current) return current; const next = copyStandard(current); mutate(next); return next })
  }
  const addNode = (parentId?: string) => changeEditor(value => {
    const labelId = nextCode(value.labels.labels.map(item => item.label_id), 'L')
    const ruleId = nextCode(value.definition_rules.map(item => item.rule_id), 'D')
    value.labels.labels.push({ label_id: labelId, parent_id: parentId || null, name: '', description: '', source_refs: [] })
    value.definition_rules.push({ rule_id: ruleId, label_id: labelId, definition: '', include: [], exclude: [], source_refs: [] })
  })
  const removeNode = (labelId: string) => changeEditor(value => {
    const removed = new Set([labelId])
    let changed = true
    while (changed) { changed = false; value.labels.labels.forEach(item => { if (item.parent_id && removed.has(item.parent_id) && !removed.has(item.label_id)) { removed.add(item.label_id); changed = true } }) }
    value.labels.labels = value.labels.labels.filter(item => !removed.has(item.label_id))
    value.definition_rules = value.definition_rules.filter(item => !removed.has(item.label_id))
    value.decision_rules.boundary_rules = value.decision_rules.boundary_rules.filter(item => !item.label_ids.some(id => removed.has(id)) && (!item.scope_label_id || !removed.has(item.scope_label_id)))
    value.decision_rules.priority_rules = value.decision_rules.priority_rules.filter(item => !item.scope_label_id || !removed.has(item.scope_label_id))
  })
  const saveVersion = async () => {
    if (!detail || !editor || !reason.trim()) return notify('请填写修改原因', true)
    setBusy(true)
    try {
      const unresolved = editor.conflicts.filter(item => !conflictResolutions[item.conflict_id])
      if (editor.conflicts.length && unresolved.length) return notify(`请先处理 ${unresolved.length} 条冲突`, true)
      const resolvedEditor = copyStandard(editor)
      resolvedEditor.conflicts = []
      Object.entries(conflictResolutions).forEach(([conflictId, resolution]) => {
        const conflict = editor.conflicts.find(item => item.conflict_id === conflictId)
        const candidate = conflict?.candidates?.[0]
        if (!candidate) return
        const target = resolvedEditor.decision_rules.boundary_rules.find(rule => rule.rule_id === candidate.rule_id)
        if (target) { target.condition = resolution.condition; target.decision = resolution.decision }
      })
      const result = await api.saveStandardVersion(detail.id, resolvedEditor, reason.trim(), true)
      setEditor(null)
      setReason('')
      setConflictResolutions({})
      setSelectedId(result.standard.id)
      await refresh()
      await load(result.standard.id)
      notify(result.validation.valid ? `已保存 v${result.standard.version}` : `已保存 v${result.standard.version}，当前不可激活`)
    } catch (error) { notify(String(error), true) } finally { setBusy(false) }
  }

  const compiled = detail?.compiled
  const definitions = new Map(compiled?.definition_rules.map(rule => [rule.label_id, rule]) || [])
  const openConflictEditor = () => {
    if (!compiled) return
    setEditor(copyStandard(compiled)); setReason('处理来源冲突'); setConflictResolutions({})
  }
  return <>
    <PageHead title="标准" meta="文档来源、层级标签与不可变版本">
      <div className="actions"><a className="btn ghost" href={api.standardTemplateUrl} download="standard-template.txt" title="下载标准文档模板"><FileDown size={15} />下载标准模板</a><button className="btn primary" onClick={() => openUpload()}><Upload size={15} />上传标准</button></div>
    </PageHead>
    <div className="two-col standards-layout">
      <div className="panel"><div className="panel-head"><h2>版本</h2><span className="count">{standards.length}</span></div>
        {standards.length ? <div className="list">{standards.map(item => <button className={`list-item standard-item ${selectedId === item.id ? 'selected' : ''}`} key={item.id} onClick={() => setSelectedId(item.id)}><div className="list-title">{item.name}</div><div className="list-meta"><span>v{item.version}</span><Badge value={item.status} /><span>{item.counts.labels} 叶子</span></div></button>)}</div> : <Empty title="暂无标准" />}
      </div>
      <div className="panel standard-detail">{detail && compiled ? <>
        <div className="panel-head"><div><h2>{detail.name} <span className="muted">v{detail.version}</span></h2><div className="list-meta"><Badge value={detail.status} /><span>{detail.counts.nodes || compiled.labels.labels.length} 节点</span><span>{detail.counts.labels} 叶子</span><span>{date(detail.created_at)}</span></div></div><div className="actions"><button className="btn ghost" onClick={() => openUpload(detail)}><Upload size={15} />补充文档</button><button className="btn ghost" onClick={() => { setEditor(copyStandard(compiled)); setReason(''); setConflictResolutions({}) }}><Pencil size={15} />编辑新版本</button>{detail.status !== 'active' && <><button className="btn primary" disabled={!detail.validation?.valid || busy} onClick={() => void activate()}><Check size={15} />激活</button><button className="btn danger" disabled={busy} onClick={() => void deleteSelected()} title="删除标准版本"><Trash2 size={15} />删除</button></>}</div></div>
        {detail.validation && detail.validation.issues.length > 0 && <div className={`validation-block ${detail.validation.valid ? 'warning' : ''}`}><div className="validation-title"><AlertTriangle size={16} />{detail.validation.valid ? '校验警告' : '校验未通过'}</div>{detail.validation.issues.map((issue, index) => <button className="validation-issue" key={`${issue.code}-${index}`} onClick={issue.code === 'SOURCE_CONFLICT' ? openConflictEditor : undefined}><code>{issue.code}</code><span>{issue.message}</span>{issue.code === 'SOURCE_CONFLICT' && <ChevronRight size={14} />}</button>)}</div>}
        <div className="tabs"><button className={tab === 'taxonomy' ? 'active' : ''} onClick={() => setTab('taxonomy')}>标签树</button><button className={tab === 'decisions' ? 'active' : ''} onClick={() => setTab('decisions')}>决策规则</button><button className={tab === 'sources' ? 'active' : ''} onClick={() => setTab('sources')}>来源</button><button className={tab === 'history' ? 'active' : ''} onClick={() => setTab('history')}>变更</button><button className={tab === 'yaml' ? 'active' : ''} onClick={() => setTab('yaml')}>YAML</button></div>
        {tab === 'taxonomy' && <div className="taxonomy-list">{compiled.labels.labels.map(label => { const path = nodePath(compiled, label.label_id); const rule = definitions.get(label.label_id); const depth = path.split('/').length - 1; const isLeaf = !compiled.labels.labels.some(item => item.parent_id === label.label_id); return <div className="taxonomy-row" key={label.label_id} style={{ paddingLeft: 18 + depth * 24 }}><div className="taxonomy-main"><GitBranch size={15} /><strong>{label.name}</strong><code>{label.label_id}</code>{isLeaf && <span className="leaf-tag">叶子</span>}<span className="muted">{path}</span></div><p>{label.description}</p>{rule && <div className="rule-summary"><span className="rule-chip">{rule.rule_id}</span><span>{rule.definition}</span></div>}</div> })}</div>}
        {tab === 'decisions' && <div className="rule-sections"><section><h3>Boundary</h3>{compiled.decision_rules.boundary_rules.length ? compiled.decision_rules.boundary_rules.map(rule => <div className="rule-row" key={rule.rule_id}><div><span className="rule-chip">{rule.rule_id}</span> {rule.label_ids.map(id => nodePath(compiled, id)).join(' ↔ ')}</div><strong>{rule.condition}</strong><p>{rule.decision}</p></div>) : <Empty title="暂无 Boundary Rule" />}</section><section><h3>Priority</h3>{compiled.decision_rules.priority_rules.length ? compiled.decision_rules.priority_rules.map(rule => <div className="rule-row" key={rule.rule_id}><span className="rule-chip">{rule.rule_id}</span>{rule.scope_label_id && <span className="muted">{nodePath(compiled, rule.scope_label_id)}</span>}<p>{rule.principle}</p></div>) : <Empty title="暂无 Priority Rule" />}</section></div>}
        {tab === 'sources' && <div className="source-list">{detail.sources?.length ? detail.sources.map(source => <div className="source-row" key={source.id}><FileCode2 size={17} /><div><strong>{source.filename}</strong><div className="list-meta"><Badge value={source.role || 'auto'} /><span>{source.media_type}</span><span>{date(source.created_at)}</span><code>{source.sha256.slice(0, 10)}</code></div></div></div>) : <Empty title="旧版本没有独立来源记录" />}</div>}
        {tab === 'history' && <div className="change-list">{detail.changes?.length ? detail.changes.map(change => <div className="change-row" key={change.id}><span className={`change-op ${change.operation}`}>{change.operation}</span><strong>{change.entity_type}</strong><code>{change.entity_id || '-'}</code><span>{change.reason || detail.change_summary || '-'}</span><time>{date(change.created_at)}</time></div>) : <Empty title="当前版本没有变更明细" />}</div>}
        {tab === 'yaml' && <div className="yaml-grid">{Object.entries(detail.files || {}).map(([filename, content]) => <div key={filename}><h3>{filename}</h3><pre>{content}</pre></div>)}</div>}
      </> : <Empty title="选择一个标准版本" />}</div>
    </div>
    {uploadOpen && <Modal title={uploadBase ? '补充标准文档' : '上传标准文档'} onClose={() => setUploadOpen(false)} footer={<><button className="btn ghost" onClick={() => setUploadOpen(false)}>取消</button><button className="btn primary" disabled={busy || !files.length || !uploadName.trim()} onClick={() => void runCompile()}>{busy ? <Spinner /> : <Sparkles size={15} />}编译新版本</button></>}><div className="field"><label>标准名称</label><input className="input" value={uploadName} disabled={Boolean(uploadBase)} onChange={event => setUploadName(event.target.value)} /></div><label className="file-drop"><Upload size={22} /><span>选择标准文档</span><small>MD、TXT、DOCX、PDF、CSV、XLSX</small><input type="file" multiple accept=".md,.txt,.docx,.pdf,.csv,.xlsx" onChange={event => { const selected = Array.from(event.target.files || []); setFiles(selected); setFileRoles(selected.map(file => inferRole(file.name))) }} /></label>{files.length > 0 && <div className="selected-files">{files.map((file, index) => <div className="selected-file" key={`${file.name}-${file.size}`}><span>{file.name}</span><select className="select" value={fileRoles[index] || 'auto'} onChange={event => setFileRoles(current => current.map((role, i) => i === index ? event.target.value as DocumentRole : role))}><option value="auto">自动识别</option><option value="definition">分类定义</option><option value="boundary">混淆边界</option><option value="priority">优先级规则</option></select></div>)}</div>}</Modal>}
    {editor && <Modal wide title="编辑并创建新版本" onClose={() => setEditor(null)} footer={<><div className="field reason-field"><label>修改原因</label><input className="input" value={reason} onChange={event => setReason(event.target.value)} /></div><button className="btn ghost" onClick={() => setEditor(null)}>取消</button><button className="btn primary" disabled={busy || !reason.trim()} onClick={() => void saveVersion()}>{busy ? <Spinner /> : <Save size={15} />}保存新版本</button></>}>
      {editor.conflicts.length > 0 && <div className="conflict-review"><div><strong>需要处理的冲突</strong>{editor.conflicts.map(conflict => <ConflictEditor key={conflict.conflict_id} conflict={conflict} resolution={conflictResolutions[conflict.conflict_id]} onResolve={value => setConflictResolutions(current => ({ ...current, [conflict.conflict_id]: value }))} />)}</div></div>}
      <div className="editor-toolbar"><h3>标签与 Definition</h3><button className="btn ghost" onClick={() => addNode()}><Plus size={15} />根标签</button></div>
      <div className="editor-nodes">{editor.labels.labels.map(label => { const rule = editor.definition_rules.find(item => item.label_id === label.label_id); const descendants = new Set(editor.labels.labels.filter(item => nodePath(editor, item.label_id).startsWith(`${nodePath(editor, label.label_id)}/`)).map(item => item.label_id)); return <section className="editor-node" key={label.label_id}><div className="editor-node-head"><div><code>{label.label_id}</code><strong>{nodePath(editor, label.label_id)}</strong></div><div className="actions"><button className="btn icon ghost" title="添加子标签" onClick={() => addNode(label.label_id)}><Plus size={15} /></button><button className="btn icon danger" title="删除标签及子标签" onClick={() => removeNode(label.label_id)}><Trash2 size={15} /></button></div></div><div className="field-row"><div className="field"><label>名称</label><input className="input" value={label.name} onChange={event => changeEditor(value => { const target = value.labels.labels.find(item => item.label_id === label.label_id); if (target) target.name = event.target.value })} /></div><div className="field"><label>父节点</label><select className="select" value={label.parent_id || ''} onChange={event => changeEditor(value => { const target = value.labels.labels.find(item => item.label_id === label.label_id); if (target) target.parent_id = event.target.value || null })}><option value="">根节点</option>{editor.labels.labels.filter(item => item.label_id !== label.label_id && !descendants.has(item.label_id)).map(item => <option value={item.label_id} key={item.label_id}>{nodePath(editor, item.label_id)}</option>)}</select></div></div><div className="field"><label>简述</label><input className="input" value={label.description} onChange={event => changeEditor(value => { const target = value.labels.labels.find(item => item.label_id === label.label_id); if (target) target.description = event.target.value })} /></div>{rule && <><div className="field"><label>{rule.rule_id} Definition</label><textarea className="textarea compact" value={rule.definition} onChange={event => changeEditor(value => { const target = value.definition_rules.find(item => item.rule_id === rule.rule_id); if (target) target.definition = event.target.value })} /></div><div className="field-row"><ListField label="Include（正例）" value={rule.include} onChange={items => changeEditor(value => { const target = value.definition_rules.find(item => item.rule_id === rule.rule_id); if (target) target.include = items })} /><ListField label="Exclude（反例）" value={rule.exclude} onChange={items => changeEditor(value => { const target = value.definition_rules.find(item => item.rule_id === rule.rule_id); if (target) target.exclude = items })} /></div></>}</section>})}</div>
      <div className="editor-toolbar"><h3>Boundary Rules</h3><button className="btn ghost" onClick={() => changeEditor(value => { const labels = value.labels.labels.slice(0, 2).map(item => item.label_id); value.decision_rules.boundary_rules.push({ rule_id: nextCode(value.decision_rules.boundary_rules.map(item => item.rule_id), 'B'), label_ids: labels, scope_label_id: null, condition: '', decision: '', source_refs: [] }) })}><Plus size={15} />Boundary</button></div>
      <div className="editor-rules">{editor.decision_rules.boundary_rules.map(rule => <section className="editor-rule" key={rule.rule_id}><div className="editor-node-head"><code>{rule.rule_id}</code><button className="btn icon danger" onClick={() => changeEditor(value => { value.decision_rules.boundary_rules = value.decision_rules.boundary_rules.filter(item => item.rule_id !== rule.rule_id) })}><Trash2 size={15} /></button></div><div className="field-row"><div className="field"><label>比较节点</label><select multiple className="select multi" value={rule.label_ids} onChange={event => changeEditor(value => { const target = value.decision_rules.boundary_rules.find(item => item.rule_id === rule.rule_id); if (target) target.label_ids = Array.from(event.currentTarget.selectedOptions, option => option.value) })}>{editor.labels.labels.map(item => <option value={item.label_id} key={item.label_id}>{nodePath(editor, item.label_id)}</option>)}</select></div><div className="field"><label>作用域</label><select className="select" value={rule.scope_label_id || ''} onChange={event => changeEditor(value => { const target = value.decision_rules.boundary_rules.find(item => item.rule_id === rule.rule_id); if (target) target.scope_label_id = event.target.value || null })}><option value="">全局</option>{editor.labels.labels.map(item => <option value={item.label_id} key={item.label_id}>{nodePath(editor, item.label_id)}</option>)}</select></div></div><div className="field"><label>条件</label><input className="input" value={rule.condition} onChange={event => changeEditor(value => { const target = value.decision_rules.boundary_rules.find(item => item.rule_id === rule.rule_id); if (target) target.condition = event.target.value })} /></div><div className="field"><label>决策</label><textarea className="textarea compact" value={rule.decision} onChange={event => changeEditor(value => { const target = value.decision_rules.boundary_rules.find(item => item.rule_id === rule.rule_id); if (target) target.decision = event.target.value })} /></div></section>)}</div>
      <div className="editor-toolbar"><h3>Priority Rules</h3><button className="btn ghost" onClick={() => changeEditor(value => { value.decision_rules.priority_rules.push({ rule_id: nextCode(value.decision_rules.priority_rules.map(item => item.rule_id), 'P'), principle: '', scope_label_id: null, source_refs: [] }) })}><Plus size={15} />Priority</button></div>
      <div className="editor-rules">{editor.decision_rules.priority_rules.map(rule => <section className="editor-rule" key={rule.rule_id}><div className="editor-node-head"><code>{rule.rule_id}</code><button className="btn icon danger" onClick={() => changeEditor(value => { value.decision_rules.priority_rules = value.decision_rules.priority_rules.filter(item => item.rule_id !== rule.rule_id) })}><Trash2 size={15} /></button></div><div className="field"><label>作用域</label><select className="select" value={rule.scope_label_id || ''} onChange={event => changeEditor(value => { const target = value.decision_rules.priority_rules.find(item => item.rule_id === rule.rule_id); if (target) target.scope_label_id = event.target.value || null })}><option value="">全局</option>{editor.labels.labels.map(item => <option value={item.label_id} key={item.label_id}>{nodePath(editor, item.label_id)}</option>)}</select></div><div className="field"><label>原则</label><textarea className="textarea compact" value={rule.principle} onChange={event => changeEditor(value => { const target = value.decision_rules.priority_rules.find(item => item.rule_id === rule.rule_id); if (target) target.principle = event.target.value })} /></div></section>)}</div>
    </Modal>}
  </>
}

function ListField({ label, value, onChange }: { label: string; value: string[]; onChange: (value: string[]) => void }) {
  return <div className="field"><label>{label}</label><textarea className="textarea compact" value={value.join('\n')} onChange={event => onChange(event.target.value.split('\n').map(item => item.trim()).filter(Boolean))} /></div>
}

function ConflictEditor({ conflict, resolution, onResolve }: { conflict: import('./types').CompilationConflict; resolution?: { condition: string; decision: string }; onResolve: (value: { condition: string; decision: string }) => void }) {
  const first = conflict.candidates?.[0]
  const second = conflict.candidates?.[1]
  const sourceText = (candidate?: { source_refs: import('./types').SourceReference[] }) => candidate?.source_refs?.length
    ? candidate.source_refs.map(ref => `${ref.filename}${ref.locator ? ` · ${ref.locator}` : ''}`).join('；')
    : '来源位置未记录（历史冲突）'
  const choose = (candidate?: { condition: string; decision: string }) => {
    if (candidate) onResolve({ condition: candidate.condition, decision: candidate.decision })
  }
  const initialCondition = resolution?.condition ?? first?.condition ?? ''
  const initialDecision = resolution?.decision ?? first?.decision ?? ''
  return <section className="conflict-item"><div className="conflict-item-head"><strong>{conflict.entity_key}</strong><Badge value={resolution ? '已处理' : '待处理'} /></div>{first && <div className="conflict-candidate"><div className="list-meta"><span>候选 A</span><code>{first.rule_id || '-'}</code></div><p><b>来源：</b>{sourceText(first)}</p><p><b>条件：</b>{first.condition}</p><p><b>决策：</b>{first.decision}</p><button className="btn ghost" onClick={() => choose(first)}>采用 A</button></div>}{second && <div className="conflict-candidate"><div className="list-meta"><span>候选 B</span><code>{second.rule_id || '-'}</code></div><p><b>来源：</b>{sourceText(second)}</p><p><b>条件：</b>{second.condition}</p><p><b>决策：</b>{second.decision}</p><button className="btn ghost" onClick={() => choose(second)}>采用 B</button></div>}{conflict.source_excerpts?.map((item, index) => <div className="conflict-excerpt" key={`${item.filename}-${index}`}><div className="list-meta"><span>原文依据</span><strong>{item.filename}</strong><span>{item.locator}</span></div><pre>{item.excerpt}</pre></div>)}{!first && !conflict.source_excerpts?.length && <div className="notice">未找到对应原文片段，请重新上传该边界规则文档以生成可审核的冲突快照。</div>}<div className="field"><label>最终规则（可基于上方来源改写）</label><textarea className="textarea compact" value={initialCondition} placeholder="条件" onChange={event => onResolve({ condition: event.target.value, decision: initialDecision })} /><textarea className="textarea compact" value={initialDecision} placeholder="决策" onChange={event => onResolve({ condition: initialCondition, decision: event.target.value })} /></div></section>
}

function DatasetsPage({ datasets, standards, refresh, notify, setPage }: { datasets: Dataset[]; standards: StandardSummary[]; refresh: () => Promise<void>; notify: (text: string, error?: boolean) => void; setPage: (page: Page) => void }) {
  const [selectedId, setSelectedId] = useState(datasets[0]?.id || '')
  const [items, setItems] = useState<Array<{ id: string; source_id?: string; text: string; gold_label?: string }>>([])
  const [standardId, setStandardId] = useState(standards.find(item => item.status === 'active')?.id || '')
  const [concurrency, setConcurrency] = useState(4)
  const [traceReplicas, setTraceReplicas] = useState(3)
  const [file, setFile] = useState<File | null>(null)
  const [datasetName, setDatasetName] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (!selectedId && datasets[0]) setSelectedId(datasets[0].id) }, [datasets, selectedId])
  useEffect(() => { if (selectedId) void api.datasetItems(selectedId).then(setItems).catch(error => notify(error.message, true)) }, [selectedId, notify])
  async function upload() { if (!file) return; setBusy(true); try { const result = await api.uploadDataset(file, datasetName); notify(`已导入 ${result.item_count} 条数据`); await refresh(); setSelectedId(result.id); setFile(null) } catch (error) { notify(error instanceof Error ? error.message : '上传失败', true) } finally { setBusy(false) } }
  async function demo() { setBusy(true); try { const result = await api.createDemoDataset(); notify(`已导入 ${result.item_count} 条演示数据`); await refresh(); setSelectedId(result.id) } catch (error) { notify(error instanceof Error ? error.message : '导入失败', true) } finally { setBusy(false) } }
  async function removeDataset(dataset: Dataset) {
    if (!window.confirm(`确定删除「${dataset.name}」吗？\n\n未使用过的数据集可以删除；已有标注运行的数据集会被系统拒绝。`)) return
    setBusy(true)
    try {
      await api.deleteDataset(dataset.id)
      const remaining = datasets.filter(item => item.id !== dataset.id)
      setSelectedId(remaining[0]?.id || '')
      setItems([])
      await refresh()
      notify(`已删除 ${dataset.name}`)
    } catch (error) { notify(error instanceof Error ? error.message : '删除数据集失败', true) } finally { setBusy(false) }
  }
  async function downloadTemplate() {
    try {
      const content = await api.datasetTemplate()
      const blob = new Blob([`\ufeff${content}`], { type: 'text/csv;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'dataset-template.csv'
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (error) { notify(error instanceof Error ? error.message : '获取数据模板失败', true) }
  }
  async function start() { if (!selectedId || !standardId) return; setBusy(true); try { await api.createRun(selectedId, standardId, concurrency, traceReplicas); notify(`标注运行已创建，并行度 ${concurrency}，每条 ${traceReplicas} 条 Trace`); await refresh(); setPage('runs') } catch (error) { notify(error instanceof Error ? error.message : '创建运行失败', true) } finally { setBusy(false) } }
  return <>
    <PageHead title="数据集" meta={`${datasets.reduce((sum, item) => sum + item.item_count, 0)} 条数据`}><div className="actions"><button className="btn ghost" onClick={() => void downloadTemplate()} title="下载 CSV 数据模板"><FileDown size={15} />数据模板</button><button className="btn" disabled={busy} onClick={() => void demo()}><FlaskConical size={15} />导入演示数据</button></div></PageHead>
    <div className="panel" style={{ marginBottom: 16 }}><div className="panel-body"><div className="field-row dataset-upload-grid"><div className="field"><label>数据文件</label><input className="input" type="file" accept=".csv,.xlsx,.txt,.jsonl,.ndjson" onChange={event => setFile(event.target.files?.[0] || null)} /></div><div className="field"><label>数据集名称</label><input className="input" value={datasetName} placeholder={file?.name.replace(/\.[^.]+$/, '') || ''} onChange={event => setDatasetName(event.target.value)} /></div><button className="btn primary" style={{ alignSelf: 'end' }} disabled={!file || busy} onClick={() => void upload()}>{busy ? <Spinner /> : <Upload size={15} />}导入</button></div><div className="hint dataset-upload-hint">推荐 CSV；模板包含 text 和可选 gold_label，TXT 每行一条 text</div><div className="dataset-format-help"><strong>字段说明：</strong><code>text</code> 是待分类文本；<code>gold_label</code> 是可选的人工真实标签，用于评估和规则改进。模板中的 <code>gold_label</code> 可以留空。</div></div></div>
    <div className="split">
      <div className="panel">{datasets.length ? <div className="list">{datasets.map(item => <div className={`list-item dataset-list-item ${selectedId === item.id ? 'selected' : ''}`} key={item.id} onClick={() => setSelectedId(item.id)}><div><div className="list-title">{item.name}</div><div className="list-meta"><span>{item.item_count} Cases</span><span>{item.filename || '内置数据'}</span><span>{date(item.created_at)}</span></div></div><button className="btn icon danger" disabled={busy} onClick={event => { event.stopPropagation(); void removeDataset(item) }} title="删除数据集"><Trash2 size={15} /></button></div>)}</div> : <Empty icon={Database} title="暂无数据集" />}</div>
      <div className="stack">
        <div className="panel"><div className="panel-head"><h2>创建标注运行</h2></div><div className="panel-body"><div className="field-row"><div className="field"><label>当前数据集</label><select className="select" value={selectedId} onChange={event => setSelectedId(event.target.value)}><option value="">选择数据集</option>{datasets.map(item => <option key={item.id} value={item.id}>{item.name} · {item.item_count}</option>)}</select></div><div className="field"><label>Standard</label><select className="select" value={standardId} onChange={event => setStandardId(event.target.value)}><option value="">选择已激活版本</option>{standards.filter(item => item.status === 'active').map(item => <option key={item.id} value={item.id}>{item.name} v{item.version}</option>)}</select></div><div className="field"><label>Query 并行度</label><select className="select" value={concurrency} onChange={event => setConcurrency(Number(event.target.value))}>{[1, 2, 4, 8, 16].map(value => <option key={value} value={value}>{value === 1 ? '1 · 串行' : `${value} 条并行`}</option>)}</select></div><div className="field"><label>每条 Trace 副本</label><select className="select" value={traceReplicas} onChange={event => setTraceReplicas(Number(event.target.value))}>{[1, 2, 3, 4, 5].map(value => <option key={value} value={value}>{value === 1 ? '1 · 单次' : `${value} 条 Trace`}</option>)}</select></div></div><div className="hint" style={{ marginTop: 8 }}>每条 query 先独立生成多条相同 Prompt 的 Annotator Trace，再由 Verifier 仲裁。副本数和 Query 并行度都会放大千帆请求速率。</div><div className="actions" style={{ marginTop: 14, justifyContent: 'flex-end' }}><button className="btn primary" disabled={!selectedId || !standardId || busy} onClick={() => void start()}>{busy ? <Spinner /> : <Play size={15} />}开始标注</button></div></div></div>
        <div className="panel"><div className="panel-head"><h2>数据预览</h2><span className="hint">内部 ID 已生成</span></div>{items.length ? <div className="table-wrap" style={{ maxHeight: 470 }}><table><thead><tr><th>ID</th><th>文本</th><th>Gold Label</th></tr></thead><tbody>{items.map(item => <tr key={item.id}><td><span className="rule-chip">{item.id.slice(0, 8)}</span></td><td className="text-cell">{item.text}</td><td>{item.gold_label || '-'}</td></tr>)}</tbody></table></div> : <Empty title="选择数据集查看内容" />}</div>
      </div>
    </div>
  </>
}

type TokenSummary = { input: number; output: number; total: number; cached: number; reasoning: number; cost: number }
type ModelSummary = TokenSummary & { calls: number; duration: number; models: string[]; retries: number; failures: number }
type QueryMonitor = {
  id: string
  text: string
  status: string
  stage: string
  route?: Route
  label?: string
  decisionStatus?: Annotation['decision']['status']
  confidence?: number
  duration: number | null
  tokens: TokenSummary
  annotator: ModelSummary
  stages: string[]
  events: TraceEvent[]
  modelCalls: ModelCall[]
}

const monitorStageOrder = ['QUERY', 'DISCLOSURE', 'ANNOTATOR', 'ANNOTATOR_VALIDATE', 'ROUTER', 'VERIFIER', 'PERSIST']
const modelPricing: Record<string, { input: number; output: number }> = {
  'deepseek-v4-flash-0731': { input: 0.001, output: 0.002 },
  'qwen3-embedding-8b': { input: 0.0005, output: 0.0005 },
}

function emptyTokenSummary(): TokenSummary { return { input: 0, output: 0, total: 0, cached: 0, reasoning: 0, cost: 0 } }
function emptyModelSummary(): ModelSummary { return { ...emptyTokenSummary(), calls: 0, duration: 0, models: [], retries: 0, failures: 0 } }
function addCall(summary: ModelSummary, call: ModelCall) {
  summary.calls += 1
  summary.duration += call.duration_ms || 0
  summary.input += call.input_tokens || 0
  summary.output += call.output_tokens || 0
  summary.total += call.total_tokens ?? ((call.input_tokens || 0) + (call.output_tokens || 0))
  summary.cached += call.cached_input_tokens || 0
  summary.reasoning += call.reasoning_tokens || 0
  const pricing = call.model_id ? modelPricing[call.model_id] : undefined
  if (pricing) summary.cost += ((call.input_tokens || 0) * pricing.input + (call.output_tokens || 0) * pricing.output) / 1000
  if (call.model_id && !summary.models.includes(call.model_id)) summary.models.push(call.model_id)
  if ((call.attempt || 1) > 1) summary.retries += 1
  if (call.status !== 'success') summary.failures += 1
}
function aggregateCalls(calls: ModelCall[]): { total: TokenSummary; annotator: ModelSummary } {
  const total = emptyTokenSummary(); const annotator = emptyModelSummary()
  calls.forEach(call => {
    total.input += call.input_tokens || 0
    total.output += call.output_tokens || 0
    total.total += call.total_tokens ?? ((call.input_tokens || 0) + (call.output_tokens || 0))
    total.cached += call.cached_input_tokens || 0
    total.reasoning += call.reasoning_tokens || 0
    const pricing = call.model_id ? modelPricing[call.model_id] : undefined
    if (pricing) total.cost += ((call.input_tokens || 0) * pricing.input + (call.output_tokens || 0) * pricing.output) / 1000
    if (call.model_role === 'annotator') addCall(annotator, call)
  })
  return { total, annotator }
}
function queryMonitors(items: Array<{ id: string; text: string }>, detail: RunDetail | null): QueryMonitor[] {
  if (!detail) return []
  const annotations = new Map(detail.annotations.map(item => [item.item_id, item]))
  const itemIds = new Set(items.map(item => item.id))
  detail.events.forEach(event => { if (event.item_id) itemIds.add(event.item_id) })
  detail.model_calls.forEach(call => { if (call.item_id) itemIds.add(call.item_id) })
  const itemText = new Map(items.map(item => [item.id, item.text]))
  return Array.from(itemIds).map(id => {
    const events = detail.events.filter(event => event.item_id === id).sort((a, b) => a.sequence - b.sequence)
    const modelCalls = detail.model_calls.filter(call => call.item_id === id)
    const annotation = annotations.get(id)
    const queryStart = events.find(event => event.stage === 'QUERY' && event.event_type === 'STAGE_STARTED')
    const queryEnd = events.find(event => event.stage === 'QUERY' && event.event_type === 'STAGE_COMPLETED')
    const started = queryStart ? new Date(queryStart.created_at).getTime() : 0
    const ended = queryEnd ? new Date(queryEnd.created_at).getTime() : Date.now()
    const lastEvent = events[events.length - 1]
    const completed = Boolean(annotation || queryEnd)
    // Under parallelism the run has no single current item, so "running" means
    // this query has emitted events but has not finished yet.
    const running = !completed && events.length > 0
    const stage = completed ? 'COMPLETED' : lastEvent?.stage || 'QUEUED'
    const stages = Array.from(new Set(events.filter(event => event.stage !== 'RUN').map(event => event.stage)))
      .sort((a, b) => monitorStageOrder.indexOf(a) - monitorStageOrder.indexOf(b))
    const summaries = aggregateCalls(modelCalls)
    return {
      id, text: itemText.get(id) || `Item ${id.slice(0, 8)}`, status: completed ? (annotation?.route || 'completed') : running ? 'running' : 'queued',
      stage, route: annotation?.route, label: annotation?.label, decisionStatus: annotation?.decision.status, confidence: annotation?.confidence,
      duration: started ? Math.max(0, ended - started) : null, tokens: summaries.total,
      annotator: summaries.annotator, stages, events, modelCalls,
    }
  }).sort((a, b) => {
    const ai = items.findIndex(item => item.id === a.id); const bi = items.findIndex(item => item.id === b.id)
    return (ai < 0 ? Number.MAX_SAFE_INTEGER : ai) - (bi < 0 ? Number.MAX_SAFE_INTEGER : bi)
  })
}
function tokenText(tokens: TokenSummary) { return `输入 ${tokens.input.toLocaleString()} · 输出 ${tokens.output.toLocaleString()} · 缓存 ${tokens.cached.toLocaleString()}` }
function wallClockDuration(detail: RunDetail | null) {
  if (!detail) return 0
  const started = new Date(detail.run.created_at).getTime()
  const ended = detail.run.completed_at ? new Date(detail.run.completed_at).getTime() : Date.now()
  return Math.max(0, ended - started)
}
function costText(value: number) { return `¥${value.toFixed(4)}` }
function modelSummaryText(summary: ModelSummary) { return `${summary.calls} 次 · ${ms(summary.duration)} · ${tokenText(summary)} · ${costText(summary.cost)}` }

const diagnosisLabels: Record<string, string> = {
  CONSENSUS: '三条一致', MAJORITY: '多数仲裁', MULTI_INTENT: '多意图',
  UNCLEAR_EXPRESSION: '表达不清', SPEC_GAP: '标准缺口', INVALID: '结果无效',
}
function VerifierPanel({ verifier }: { verifier: Annotation['verifier'] }) {
  if (!verifier) return <div className="muted">未记录 Verifier 结果（历史运行或单 Trace 模式）</div>
  const diagnosis = verifier.diagnosis || verifier.outcome
  const feedback = verifier.standard_feedback
  return <div className="trace-verifier">
    <div className="trace-verifier-head"><strong>Verifier 诊断</strong><Badge value={diagnosisLabels[diagnosis] || diagnosis} /></div>
    <div className="trace-verifier-grid"><span>最终标签</span><strong>{verifier.labels?.length ? verifier.labels.join('、') : verifier.label || '-'}</strong><span>置信度</span><strong>{verifier.confidence == null ? '-' : verifier.confidence.toFixed(2)}</strong></div>
    {verifier.reason && <p>{verifier.reason}</p>}
    {verifier.summary && verifier.summary !== verifier.reason && <p className="muted">{verifier.summary}</p>}
    {verifier.inferred_intent && <div className="trace-feedback"><b>推测意图</b><span>{verifier.inferred_intent}</span></div>}
    {feedback && <div className="trace-feedback"><b>{String(feedback.suggestion_type || '标准反馈')}</b><span>{String(feedback.proposed_change || feedback.reason || JSON.stringify(feedback))}</span></div>}
    {verifier.issues?.length ? <div className="trace-issues">{verifier.issues.map((issue, index) => <div key={index}><span className="rule-chip">{String(issue.code || 'ISSUE')}</span>{String(issue.message || '')}</div>)}</div> : null}
  </div>
}
function TraceReplicaPanel({ annotation }: { annotation: Annotation }) {
  if (!annotation.replicas?.length) return null
  return <div className="trace-replicas"><div className="trace-section-title">Annotator Trace 副本 <span className="muted">{annotation.replicas.length} 条</span></div><div className="trace-replica-grid">{annotation.replicas.map(replica => <details className="trace-replica" key={replica.replica_index} open={replica.replica_index === 1}><summary><strong>Trace {replica.replica_index}</strong><span>{replica.decision.label || '-'}</span><span>{replica.decision.confidence.toFixed(2)}</span></summary><div className="trace-replica-body"><div><b>候选</b><span>{replica.candidates.join('、') || '无'}</span></div><div><b>理由</b><span>{replica.decision.reason}</span></div><div><b>证据</b><span>{replica.decision.evidence}</span></div><div><b>Rules</b><span className="rules">{replica.decision.leaf_rule_used && <span className="rule-chip">{replica.decision.leaf_rule_used}</span>}{replica.decision.decision_rules_referenced.map(rule => <span className="rule-chip" key={rule}>{rule}</span>)}</span></div></div></details>)}</div></div>
}

function RunsPage({ runs, standards, refresh, notify }: { runs: Run[]; standards: StandardSummary[]; refresh: () => Promise<void>; notify: (text: string, error?: boolean) => void }) {
  const [selectedId, setSelectedId] = useState(runs[0]?.id || '')
  const [detail, setDetail] = useState<RunDetail | null>(null)
  const [items, setItems] = useState<Array<{ id: string; text: string }>>([])
  const [filter, setFilter] = useState<Route | 'ALL'>('ALL')
  const [annotation, setAnnotation] = useState<Annotation | null>(null)
  const [reviewLabel, setReviewLabel] = useState('')
  const [reviewNote, setReviewNote] = useState('')
  const [compareIds, setCompareIds] = useState<[string, string]>(['', ''])
  const [comparison, setComparison] = useState<{ left: { run: Run; metrics: Metrics }; right: { run: Run; metrics: Metrics } } | null>(null)
  const [retrying, setRetrying] = useState(false)
  const detailRef = useRef<RunDetail | null>(null)
  useEffect(() => { detailRef.current = detail }, [detail])
  useEffect(() => { if (!selectedId && runs[0]) setSelectedId(runs[0].id) }, [runs, selectedId])
  const loadDetail = useCallback(async () => { if (selectedId) try { setDetail(await api.run(selectedId)) } catch (error) { notify(error instanceof Error ? error.message : '加载失败', true) } }, [selectedId, notify])
  useEffect(() => {
    if (!detail?.run.dataset_id) { setItems([]); return }
    void api.datasetItems(detail.run.dataset_id).then(value => setItems(value.map(item => ({ id: item.id, text: item.text })))).catch(() => setItems([]))
  }, [detail?.run.dataset_id])
  useEffect(() => { void loadDetail() }, [loadDetail, runs])
  useEffect(() => {
    const current = detailRef.current
    if (!selectedId || !current || !['queued', 'running'].includes(current.run.status)) return
    const after = current.events.length ? current.events[current.events.length - 1].sequence : 0
    const source = new EventSource(`/api/runs/${selectedId}/events?after=${after}`)
    source.onmessage = event => {
      try {
        const trace = JSON.parse(event.data)
        setDetail(previous => {
          if (!previous || previous.events.some(item => item.id === trace.id)) return previous
          const events = [...previous.events, trace]
          let modelCalls = previous.model_calls
          const callId = trace.metadata?.model_call_id
          if (trace.event_type === 'MODEL_CALL_COMPLETED' && callId && !modelCalls.some(item => item.id === callId)) {
            const usage = trace.metadata?.usage || {}
            modelCalls = [...modelCalls, {
              id: callId, run_id: trace.run_id, item_id: trace.item_id, stage: trace.stage,
              operation: trace.metadata?.operation || 'model', attempt: trace.metadata?.attempt || 1,
              model_role: trace.model_role || undefined, model_id: trace.model_id || undefined,
              duration_ms: trace.duration_ms || 0, input_tokens: usage.input_tokens ?? null,
              output_tokens: usage.output_tokens ?? null, total_tokens: usage.total_tokens ?? null,
              cached_input_tokens: usage.cached_input_tokens ?? null, reasoning_tokens: usage.reasoning_tokens ?? null,
              request_id: trace.metadata?.request_id || null, status: trace.status,
              error: trace.metadata?.error || null, usage, created_at: trace.created_at,
            }]
          }
          const run = { ...previous.run }
          if (trace.stage === 'QUERY' && trace.event_type === 'STAGE_COMPLETED') run.processed = Math.max(run.processed, Number(trace.metadata?.completed) || run.processed)
          if (trace.stage && ['STAGE_STARTED', 'MODEL_CALL_COMPLETED'].includes(trace.event_type)) run.current_stage = trace.stage
          return { ...previous, run, events, model_calls: modelCalls }
        })
        if (trace.stage === 'QUERY' && trace.event_type === 'STAGE_COMPLETED') { void loadDetail(); void refresh() }
      } catch { /* ignore malformed event and keep the stream alive */ }
    }
    source.onerror = () => source.close()
    return () => source.close()
  }, [selectedId, detail?.run.status, loadDetail, refresh])
  async function review() { if (!annotation || !reviewLabel) return; try { await api.review(annotation.id, reviewLabel, reviewNote); notify('人工审核已保存'); setAnnotation(null); await loadDetail() } catch (error) { notify(error instanceof Error ? error.message : '保存失败', true) } }
  async function compare() { if (!compareIds[0] || !compareIds[1]) return; try { setComparison(await api.compare(compareIds[0], compareIds[1])) } catch (error) { notify(error instanceof Error ? error.message : '对比失败', true) } }
  async function retry() { if (!detail || detail.run.status !== 'failed') return; setRetrying(true); try { await api.retryRun(detail.run.id); notify(`已从 ${detail.run.processed}/${detail.run.total} 继续运行`); await refresh(); await loadDetail() } catch (error) { notify(error instanceof Error ? error.message : '继续运行失败', true) } finally { setRetrying(false) } }
  const filtered = detail?.annotations.filter(item => filter === 'ALL' || item.route === filter) || []
  const monitors = useMemo(() => queryMonitors(items, detail), [items, detail])
  const runTokens = monitors.reduce<TokenSummary>((sum, item) => ({ input: sum.input + item.tokens.input, output: sum.output + item.tokens.output, total: sum.total + item.tokens.total, cached: sum.cached + item.tokens.cached, reasoning: sum.reasoning + item.tokens.reasoning, cost: sum.cost + item.tokens.cost }), emptyTokenSummary())
  // Summing per-query durations overstates a parallel run, so the headline
  // figure is wall clock and the sum is reported separately as cumulative time.
  const runDuration = wallClockDuration(detail)
  const cumulativeDuration = monitors.reduce((sum, item) => sum + (item.duration || 0), 0)
  const annotationCallSummary = annotation ? aggregateCalls((detail?.model_calls || []).filter(call => call.item_id === annotation.item_id)) : null
  const candidatePaths = annotation?.disclosure.candidates || annotation?.disclosure.definitions.map(item => item.leaf_path) || []
  const reviewStandard = detail ? standards.find(item => item.id === detail.run.standard_id) : undefined
  return <>
    <PageHead title="标注运行" meta={`${runs.length} 次运行`}><select className="select run-selector" aria-label="选择标注运行" title="选择标注运行" value={selectedId} onChange={event => setSelectedId(event.target.value)} disabled={!runs.length}><option value="">选择运行</option>{runs.map(run => <option key={run.id} value={run.id}>{run.dataset_name} · v{run.standard_version} · {run.status}</option>)}</select>{detail?.run.status === 'completed' && <><a className="btn" href={`/api/runs/${detail.run.id}/export?format=csv`}><Upload size={15} style={{ transform: 'rotate(180deg)' }} />导出结果</a><a className="btn" href={`/api/runs/${detail.run.id}/export?format=jsonl&gold_only=true`}><ShieldCheck size={15} />导出 Gold</a></>}{detail?.run.status === 'failed' && <button className="btn primary" disabled={retrying} onClick={() => void retry()}>{retrying ? <Spinner /> : <Play size={15} />}继续运行</button>}<button className="btn" onClick={() => void refresh()}><RefreshCw size={15} />刷新</button></PageHead>
    <div className="run-detail-layout">{detail ? <>
        <div className="four-col"><div className="metric"><div className="metric-label">自动通过率</div><div className="metric-value">{pct(detail.metrics.auto_accept_rate)}</div></div><div className="metric"><div className="metric-label">准确率</div><div className="metric-value">{pct(detail.metrics.accuracy)}</div><div className="metric-foot">n={detail.metrics.accuracy_sample_size}</div></div><div className="metric"><div className="metric-label">审核率</div><div className="metric-value">{pct(detail.metrics.review_rate)}</div></div><div className="metric"><div className="metric-label">人工反馈</div><div className="metric-value">{detail.metrics.routes.REVIEW || 0}</div></div></div>
        <QueryMonitorPanel monitors={monitors} run={detail.run} runTokens={runTokens} runDuration={runDuration} cumulativeDuration={cumulativeDuration} />
        <div className="panel"><div className="panel-head"><h2>标注结果</h2><select className="select" style={{ width: 155 }} value={filter} onChange={event => setFilter(event.target.value as Route | 'ALL')}><option value="ALL">全部路由</option>{['AUTO_ACCEPT', 'REVIEW'].map(value => <option key={value}>{value}</option>)}</select></div>{filtered.length ? <div className="table-wrap" style={{ maxHeight: 620 }}><table><thead><tr><th>文本</th><th>Label</th><th>Rules</th><th>置信度</th><th>路由</th><th></th></tr></thead><tbody>{filtered.map(item => <tr key={item.id}><td className="text-cell">{item.text}</td><td>{item.human_label || item.label || '-'}</td><td><div className="rules">{item.rules_used.map(rule => <span className="rule-chip" key={rule}>{rule}</span>)}</div></td><td className="confidence">{item.confidence.toFixed(2)}</td><td><Badge value={item.route} className={item.route === 'REVIEW' && Boolean(item.human_label) ? 'reviewed' : ''} /></td><td><button className="btn icon ghost" title="查看" onClick={() => { setAnnotation(item); setReviewLabel(item.human_label || item.label || ''); setReviewNote(item.review_note || '') }}><ChevronRight size={15} /></button></td></tr>)}</tbody></table></div> : <Empty title={detail.run.status === 'completed' ? '没有匹配的标注结果' : '运行处理中'} />}</div>
      </> : <Empty title="选择一次运行" />}
    </div>
    {runs.filter(item => item.status === 'completed').length >= 2 && <div className="panel" style={{ marginTop: 16 }}><div className="panel-head"><h2>版本对比</h2><GitCompareArrows size={16} /></div><div className="panel-body"><div className="field-row" style={{ gridTemplateColumns: '1fr 1fr auto' }}><select className="select" value={compareIds[0]} onChange={event => setCompareIds([event.target.value, compareIds[1]])}><option value="">基准运行</option>{runs.filter(item => item.status === 'completed').map(item => <option key={item.id} value={item.id}>{item.dataset_name} · v{item.standard_version}</option>)}</select><select className="select" value={compareIds[1]} onChange={event => setCompareIds([compareIds[0], event.target.value])}><option value="">对比运行</option>{runs.filter(item => item.status === 'completed').map(item => <option key={item.id} value={item.id}>{item.dataset_name} · v{item.standard_version}</option>)}</select><button className="btn" onClick={() => void compare()} disabled={!compareIds[0] || !compareIds[1]}>对比</button></div>{comparison && <CompareView value={comparison} />}</div></div>}
    {annotation && <Modal title="标注详情" wide onClose={() => setAnnotation(null)} footer={<><button className="btn" onClick={() => setAnnotation(null)}>关闭</button><button className="btn primary" disabled={!reviewLabel || !reviewStandard} onClick={() => void review()}><Save size={14} />保存审核</button></>}>
      <dl className="detail-grid"><dt>文本</dt><dd>{annotation.text}</dd><dt>建议 Label</dt><dd>{annotation.label || '-'}</dd><dt>多意图标签</dt><dd>{annotation.labels?.length ? annotation.labels.join('、') : '-'}</dd><dt>路由</dt><dd><Badge value={annotation.route} /></dd><dt>判断理由</dt><dd><div className="reason-with-keys">{annotation.route_reasons.length > 0 && <div className="reason-keys">{annotation.route_reasons.map((reason, index) => <span className="rule-chip reason-key" key={`${reason.source}-${reason.code}-${index}`}>{routeReasonKey(reason)}</span>)}</div>}<div>{annotation.decision.reason}</div></div></dd><dt>原文证据</dt><dd>{annotation.evidence}</dd><dt>候选召回</dt><dd><div className="candidate-chain-list">{candidatePaths.length ? candidatePaths.map((candidate, candidateIndex) => { const definition = annotation.disclosure.definitions.find(item => item.leaf_path === candidate); const selected = candidate === annotation.label; return <div className={`candidate-chain ${selected ? 'selected' : ''}`} key={candidate}><div className="candidate-chain-head"><span className="candidate-index">候选 {candidateIndex + 1}</span><strong>{candidate}</strong>{selected && <span className="candidate-selected">当前建议</span>}</div>{definition?.chain.length ? <div className="candidate-chain-rules">{definition.chain.map((rule, index) => <div className="candidate-chain-rule" key={rule.rule_id}><span className="rule-chip">{rule.rule_id}</span><span className="candidate-level">{index === definition.chain.length - 1 ? '叶子定义' : `第 ${index + 1} 层`}</span><span>{rule.definition}</span></div>)}</div> : <div className="muted">未记录该候选的层级 Definition</div>}</div> }) : <span className="muted">没有记录候选召回结果</span>}</div></dd><dt>规则证据</dt><dd>{annotation.decision.evidence_items?.length ? <div className="stack" style={{ gap: 6 }}>{annotation.decision.evidence_items.map((item, index) => <div key={index}>{String(item.rule_id || item.type || 'evidence')}：{String(item.explanation || item.quote || item.rule_text || '')}</div>)}</div> : '暂无结构化规则证据'}</dd><dt>模型汇总</dt><dd>{annotationCallSummary && <div className="stack" style={{ gap: 5 }}><div>Annotator：{modelSummaryText(annotationCallSummary.annotator)}</div><div>总计：{tokenText(annotationCallSummary.total)} · {costText(annotationCallSummary.total.cost)}</div></div>}</dd><dt>Rules Used</dt><dd><div className="rules">{annotation.rules_used.map(rule => <span className="rule-chip" key={rule}>{rule}</span>)}</div></dd></dl>
      <VerifierPanel verifier={annotation.verifier} />
      <TraceReplicaPanel annotation={annotation} />
      <HierarchicalLabelPicker standard={reviewStandard} value={reviewLabel} onChange={setReviewLabel} />
      <div className="field"><label>审核备注</label><textarea className="textarea" value={reviewNote} onChange={event => setReviewNote(event.target.value)} /></div>
    </Modal>}
  </>
}

function HierarchicalLabelPicker({ standard, value, onChange }: { standard?: StandardSummary; value: string; onChange: (value: string) => void }) {
  const labels = useMemo(() => standard?.compiled.labels.labels || [], [standard])
  const children = useMemo(() => {
    const grouped = new Map<string, typeof labels>()
    labels.forEach(label => {
      const parent = label.parent_id || ''
      const siblings = grouped.get(parent) || []
      siblings.push(label)
      grouped.set(parent, siblings)
    })
    grouped.forEach(siblings => siblings.sort((left, right) => left.name.localeCompare(right.name, 'zh-CN')))
    return grouped
  }, [labels])
  const idByPath = useMemo(() => new Map(labels.map(label => [nodePath(standard!.compiled, label.label_id), label.label_id])), [labels, standard])
  const [selectedIds, setSelectedIds] = useState<string[]>([])

  useEffect(() => {
    if (!standard) {
      setSelectedIds([])
      return
    }
    if (!value) return
    const selectedId = idByPath.get(value)
    if (!selectedId) {
      setSelectedIds([])
      return
    }
    const byId = new Map(labels.map(label => [label.label_id, label]))
    const chain: string[] = []
    let current = byId.get(selectedId)
    while (current) {
      chain.unshift(current.label_id)
      current = current.parent_id ? byId.get(current.parent_id) : undefined
    }
    setSelectedIds(chain)
  }, [idByPath, labels, standard, value])

  function choose(level: number, labelId: string) {
    const next = [...selectedIds.slice(0, level), labelId]
    setSelectedIds(next)
    const selected = labels.find(label => label.label_id === labelId)
    const hasChildren = Boolean(selected && children.get(selected.label_id)?.length)
    onChange(!hasChildren && selected ? nodePath(standard!.compiled, selected.label_id) : '')
  }

  if (!standard) {
    return <div className="field"><label>人工 Label</label><div className="label-picker-empty">当前运行对应的 Standard 尚未加载，暂不能选择标签</div></div>
  }
  const levels: ReactNode[] = []
  let parentId = ''
  for (let level = 0; ; level += 1) {
    const options = children.get(parentId) || []
    if (!options.length) break
    const selectedAtLevel = selectedIds[level] || ''
    levels.push(<div className="field label-picker-level" key={parentId || 'root'}><label>{level === 0 ? '人工 Label' : `第 ${level + 1} 层`}</label><select className="select" value={selectedAtLevel} onChange={event => choose(level, event.target.value)}><option value="">选择{level === 0 ? '标签' : '下级标签'}</option>{options.map(label => <option value={label.label_id} key={label.label_id}>{label.name}{children.get(label.label_id)?.length ? '' : ' · 叶子'}</option>)}</select></div>)
    if (!selectedAtLevel) break
    parentId = selectedAtLevel
  }
  return <div className="label-picker"><div className="label-picker-levels">{levels}</div><div className={`hint ${value ? 'label-picker-value' : ''}`}>{value ? `已选叶子标签：${value}` : '请按层级选择，只有叶子标签可以保存审核'}</div></div>
}

function QueryMonitorPanel({ monitors, run, runTokens, runDuration, cumulativeDuration }: { monitors: QueryMonitor[]; run: Run; runTokens: TokenSummary; runDuration: number; cumulativeDuration: number }) {
  const running = monitors.filter(item => item.status === 'running')
  const concurrency = run.concurrency || 1
  return <div className="panel monitor-panel">
    <div className="panel-head"><div><h2>标注进度</h2><div className="list-meta"><Badge value={run.current_stage || run.status} />{concurrency > 1 && <span>并行度 {concurrency}</span>}{running.length === 1 ? <span>当前：{running[0].text.slice(0, 42)}{running[0].text.length > 42 ? '…' : ''}</span> : running.length > 1 ? <span>{running.length} 条并行处理中</span> : null}<span>{run.processed}/{run.total} 条</span></div></div><div className="monitor-total monitor-total-table"><div className="monitor-total-row monitor-total-head"><span>标注总耗时</span><span>累计模型耗时</span><span>输入 Token</span><span>输出 Token</span><span>缓存 Token</span><span>费用</span></div><div className="monitor-total-row monitor-total-values"><strong>{ms(runDuration)}</strong><strong>{ms(cumulativeDuration)}</strong><strong>{runTokens.input.toLocaleString()}</strong><strong>{runTokens.output.toLocaleString()}</strong><strong>{runTokens.cached.toLocaleString()}</strong><strong>{costText(runTokens.cost)}</strong></div></div></div>
    {monitors.length ? <div className="query-monitor-list"><div className="query-monitor-head"><span>文本</span><span>标注标签</span><span>路由 / 进度</span><span>耗时</span><span>Token</span><span>费用</span><span /></div>{monitors.map(item => <details className="query-monitor" key={item.id}>
      <summary className="query-monitor-summary">
        <span className="query-monitor-text" title={item.text}>{item.text}</span>
        <span className={`query-label ${item.label ? '' : 'empty-label'}`}>{item.label || (item.decisionStatus ? `未给标签 · ${item.decisionStatus}` : '待产出')}</span>
        <span className="query-state"><Badge value={item.status} /><small>{item.stage}</small></span>
        <span className="query-duration"><strong>{ms(item.duration)}</strong><small>Annotator {ms(item.annotator.duration)}</small></span>
        <span className="query-token">{tokenText(item.tokens)}</span>
        <span className="query-cost">{costText(item.tokens.cost)}</span>
      </summary>
      <div className="query-monitor-detail">
        <div className="query-flow">{(item.stages.length ? item.stages : ['QUERY']).map(stage => <span className={`query-flow-step ${stage === item.stage ? 'current' : ''}`} key={stage}>{stage}</span>)}</div>
        <div className="three-col monitor-summary-grid">
          <div className="monitor-summary"><div className="monitor-summary-title">Annotator</div><strong>{modelSummaryText(item.annotator)}</strong><small>{item.annotator.models.join(', ') || '暂无模型记录'}{item.annotator.retries ? ` · 重试 ${item.annotator.retries}` : ''}</small></div>
          <div className="monitor-summary"><div className="monitor-summary-title">Query 总计</div><strong>{ms(item.duration)} · {item.tokens.total.toLocaleString()} tokens · {costText(item.tokens.cost)}</strong><small>{item.label || '未产出标签'}{item.route ? ` · ${item.route}` : ''}{item.events.some(event => event.stage === 'VERIFIER') ? ' · Verifier 已执行' : ''}</small></div>
        </div>
        <details className="monitor-raw"><summary>查看底层阶段和模型调用明细（{item.events.length} 个事件，{item.modelCalls.length} 次请求）</summary>
          <div className="table-wrap"><table><thead><tr><th>阶段</th><th>事件</th><th>耗时</th><th>说明</th></tr></thead><tbody>{item.events.map(event => <tr key={event.id}><td><span className="rule-chip">{event.stage}</span></td><td><Badge value={event.event_type} /></td><td>{ms(event.duration_ms)}</td><td className="text-cell">{event.message}</td></tr>)}</tbody></table></div>
          {item.modelCalls.length > 0 && <div className="table-wrap monitor-call-table"><table><thead><tr><th>角色</th><th>模型</th><th>操作</th><th>耗时</th><th>输入</th><th>输出</th><th>缓存</th><th>状态</th></tr></thead><tbody>{item.modelCalls.map(call => <tr key={call.id}><td>{call.model_role || '-'}</td><td>{call.model_id || '-'}</td><td>{call.operation} #{call.attempt}</td><td>{ms(call.duration_ms)}</td><td>{call.input_tokens ?? '-'}</td><td>{call.output_tokens ?? '-'}</td><td>{call.cached_input_tokens ?? '-'}</td><td><Badge value={call.status} /></td></tr>)}</tbody></table></div>}
        </details>
      </div>
    </details>)}</div> : <Empty title="等待第一条标注开始" />}
  </div>
}

function CompareView({ value }: { value: { left: { run: Run; metrics: Metrics }; right: { run: Run; metrics: Metrics } } }) {
  const rows: Array<[string, keyof Metrics]> = [['准确率', 'accuracy'], ['自动通过率', 'auto_accept_rate'], ['人工审核率', 'review_rate']]
  return <div className="compare-grid" style={{ marginTop: 16 }}><div className="compare-head">指标</div><div className="compare-head">Standard v{value.left.run.standard_version}</div><div className="compare-head">Standard v{value.right.run.standard_version}</div>{rows.map(([label, key]) => <FragmentRow key={key} label={label} left={value.left.metrics[key] as number | null} right={value.right.metrics[key] as number | null} invert={key === 'review_rate'} />)}</div>
}
function FragmentRow({ label, left, right, invert }: { label: string; left: number | null; right: number | null; invert: boolean }) {
  const improved = left != null && right != null && (invert ? right < left : right > left)
  return <><div>{label}</div><div>{pct(left)}</div><div className={improved ? 'positive' : ''}>{pct(right)}</div></>
}

function GapsPage({ runs, refresh, notify }: { runs: Run[]; refresh: () => Promise<void>; notify: (text: string, error?: boolean) => void }) {
  const completed = runs.filter(item => item.status === 'completed')
  const [runId, setRunId] = useState(completed[0]?.id || '')
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState<Suggestion | null>(null)
  const [ruleJson, setRuleJson] = useState('')
  const [reason, setReason] = useState('')
  useEffect(() => { void api.suggestions(runId || undefined).then(setSuggestions).catch(error => notify(error.message, true)) }, [runId, notify])
  async function mine() { if (!runId) return; setBusy(true); try { const result = await api.mine(runId); setSuggestions(result.suggestions); notify(result.suggestions.length ? `生成 ${result.suggestions.length} 条建议` : '没有达到聚类阈值的失败模式') } catch (error) { notify(error instanceof Error ? error.message : '挖掘失败', true) } finally { setBusy(false) } }
  async function reviseAndRerun() {
    if (!editing) return
    const run = runs.find(value => value.id === editing.run_id); if (!run) return
    setBusy(true)
    try {
      const newRule = JSON.parse(ruleJson)
      const revised = await api.revise(run.standard_id, { rule_id: editing.payload.target_rule_id, new_rule: newRule, reason, related_case_ids: editing.case_ids, suggestion_id: editing.id })
      await api.impactRun({ source_run_id: run.id, target_standard_id: revised.standard.id, rule_id: editing.payload.target_rule_id, labels: revised.affected_labels })
      notify(`Standard v${revised.standard.version} 已生成，受影响数据开始重跑`); setEditing(null); await refresh()
    } catch (error) { notify(error instanceof Error ? error.message : '修改失败', true) } finally { setBusy(false) }
  }
  async function approveAndApply(item: Suggestion) {
    const patch = item.patch
    if (!patch) { notify('该建议没有可审批的 Rule Patch', true); return }
    setBusy(true)
    try {
      await api.updateRulePatch(patch.id, 'approved')
      const result = await api.applyRulePatch(patch.id)
      notify(`Rule Patch 已批准，Standard v${String((result.standard as { version: number }).version)} 已生成并开始重跑`)
      await refresh()
      setSuggestions(await api.suggestions(runId || undefined))
    } catch (error) { notify(error instanceof Error ? error.message : 'Rule Patch 应用失败', true) } finally { setBusy(false) }
  }
  return <>
    <PageHead title="规则进化" meta={`${suggestions.length} 条待审批建议`}><select className="select" style={{ width: 260 }} value={runId} onChange={event => setRunId(event.target.value)}><option value="">选择已完成运行</option>{completed.map(run => <option key={run.id} value={run.id}>{run.dataset_name} · Standard v{run.standard_version}</option>)}</select><button className="btn primary" disabled={!runId || busy} onClick={() => void mine()}>{busy ? <Spinner /> : <Sparkles size={15} />}基于人工反馈生成 Patch</button></PageHead>
    <div className="panel">{suggestions.length ? suggestions.map(item => <div className="suggestion" key={item.id}><div className="actions" style={{ justifyContent: 'space-between' }}><div><h3>{item.payload.title}</h3><div className="list-meta"><Badge value={item.patch?.status || item.status} />{item.payload.labels.map(label => <span key={label}>{label}</span>)}{item.payload.target_rule_id && <span className="rule-chip">{item.payload.target_rule_id}</span>}</div></div>{item.patch?.status === 'proposed' && <button className="btn primary" disabled={busy} onClick={() => void approveAndApply(item)}>批准 Patch 并重跑 <ArrowRight size={14} /></button>}</div><p><b>问题：</b>{item.payload.problem}</p><p><b>建议：</b>{item.payload.proposed_change}</p><p className="muted">Patch 操作：{item.payload.operations?.length || 0} 个，必须人工批准后才会生成新 Standard。</p><ul className="case-list">{item.payload.typical_cases.map(value => <li key={value}>{value}</li>)}</ul></div>) : <Empty icon={Lightbulb} title="暂无 Rule Patch" />}</div>
    {editing && <Modal title={`修改 ${editing.payload.target_rule_id}`} onClose={() => !busy && setEditing(null)} footer={<><button className="btn" disabled={busy} onClick={() => setEditing(null)}>取消</button><button className="btn primary" disabled={busy || !reason.trim()} onClick={() => void reviseAndRerun()}>{busy ? <Spinner /> : <Play size={14} />}生成 v2 并重跑</button></>}><div className="notice">{editing.payload.proposed_change}</div><div className="field"><label>Rule JSON</label><textarea className="textarea json" value={ruleJson} onChange={event => setRuleJson(event.target.value)} /></div><div className="field"><label>修改原因</label><textarea className="textarea" value={reason} onChange={event => setReason(event.target.value)} /></div></Modal>}
  </>
}

function SettingsPage({ health, refresh, notify }: { health: { api_key_configured: boolean } | null; refresh: () => Promise<void>; notify: (text: string, error?: boolean) => void }) {
  const [settings, setSettings] = useState<ModelSettings | null>(null)
  const [models, setModels] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  useEffect(() => { void api.settings().then(value => setSettings(value.models)).catch(error => notify(error.message, true)) }, [notify])
  async function loadModels() { setBusy(true); try { const result = await api.models(); setModels(result.data.map(item => item.id || item.model || '').filter(Boolean)); notify(`已获取 ${result.data.length} 个模型`) } catch (error) { notify(error instanceof Error ? error.message : '模型列表获取失败', true) } finally { setBusy(false) } }
  async function save() { if (!settings) return; setBusy(true); try { await api.saveSettings(settings); notify('模型设置已保存'); await refresh() } catch (error) { notify(error instanceof Error ? error.message : '保存失败', true) } finally { setBusy(false) } }
  const update = (key: keyof ModelSettings, value: string | number) => setSettings(current => current ? { ...current, [key]: value } : current)
  return <>
    <PageHead title="模型设置" meta="Qianfan ModelBuilder V2"><button className="btn" disabled={busy || !health?.api_key_configured} onClick={() => void loadModels()}>{busy ? <Spinner /> : <RefreshCw size={15} />}读取模型列表</button><button className="btn primary" disabled={busy || !settings} onClick={() => void save()}><Save size={15} />保存</button></PageHead>
    {!health?.api_key_configured && <div className="alert" style={{ marginBottom: 16 }}><AlertTriangle size={16} /><span>未检测到 QIANFAN_API_KEY。请在服务端环境变量中配置后重启 API。</span></div>}
    {settings && <div className="panel"><div className="panel-head"><h2>模块模型</h2><Badge value={health?.api_key_configured ? 'API KEY SET' : 'API KEY REQUIRED'} /></div><div className="panel-body stack"><datalist id="qianfan-models">{models.map(model => <option value={model} key={model} />)}</datalist><div className="two-col">
      {([['compiler_model', '标准编译模型'], ['annotator_model', '标注模型'], ['miner_model', '规则进化模型'], ['embedding_model', 'Embedding 模型']] as Array<[keyof ModelSettings, string]>).map(([key, label]) => <div className="field" key={key}><label>{label}</label><input className="input" list="qianfan-models" value={String(settings[key])} onChange={event => update(key, event.target.value)} /></div>)}
    </div><div className="two-col"><div className="field"><label>AUTO_ACCEPT 置信度阈值</label><input className="input" type="number" min="0" max="1" step="0.01" value={settings.auto_accept_threshold} onChange={event => update('auto_accept_threshold', Number(event.target.value))} /></div><div className="field"><label>人工反馈最小聚类数</label><input className="input" type="number" min="2" step="1" value={settings.spec_gap_min_cluster_size} onChange={event => update('spec_gap_min_cluster_size', Number(event.target.value))} /></div></div></div></div>}
  </>
}
