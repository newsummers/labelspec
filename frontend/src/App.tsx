import { useCallback, useEffect, useState, type ReactNode } from 'react'
import {
  AlertTriangle, ArrowRight, BarChart3, Check, ChevronRight, CircleGauge, Database,
  FileCode2, FileDown, FlaskConical, GitBranch, GitCompareArrows, Layers3, Lightbulb, LoaderCircle,
  Pencil, Trash2,
  Play, Plus, RefreshCw, Save, ScanSearch, Settings, ShieldCheck, Sparkles,
  Upload, X,
} from 'lucide-react'
import { api } from './api'
import type {
  Annotation, CompiledStandard, Dataset, DocumentRole, Metrics, ModelSettings, Route, Run, RunDetail, StandardSummary,
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
function Badge({ value }: { value: string }) { return <span className={`badge ${value}`}>{value}</span> }
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
          {page === 'runs' && <RunsPage runs={runs} refresh={refresh} notify={notify} />}
          {page === 'gaps' && <GapsPage runs={runs} standards={standards} refresh={refresh} notify={notify} />}
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
      <div className="metric"><div className="metric-label"><GitCompareArrows size={14} />Rule 冲突率</div><div className="metric-value">{pct(metrics?.rule_conflict_rate)}</div><div className="metric-foot">AMBIGUOUS + SPEC_GAP</div></div>
    </div>
    <div className="flow">
      {[
        ['01', 'Standard', active ? `v${active.version} · ${active.counts.labels} Labels` : '未激活'],
        ['02', 'Data', `${datasets.reduce((sum, item) => sum + item.item_count, 0)} Cases`],
        ['03', 'Model', runs[0] ? `${runs[0].processed}/${runs[0].total}` : '未运行'],
        ['04', 'Failure', `${(metrics?.routes.REVIEW || 0) + (metrics?.routes.AMBIGUOUS || 0) + (metrics?.routes.SPEC_GAP || 0)} Cases`],
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
  async function start() { if (!selectedId || !standardId) return; setBusy(true); try { await api.createRun(selectedId, standardId); notify('标注运行已创建'); await refresh(); setPage('runs') } catch (error) { notify(error instanceof Error ? error.message : '创建运行失败', true) } finally { setBusy(false) } }
  return <>
    <PageHead title="数据集" meta={`${datasets.reduce((sum, item) => sum + item.item_count, 0)} 条数据`}><div className="actions"><button className="btn ghost" onClick={() => void downloadTemplate()} title="下载 CSV 数据模板"><FileDown size={15} />数据模板</button><button className="btn" disabled={busy} onClick={() => void demo()}><FlaskConical size={15} />导入演示数据</button></div></PageHead>
    <div className="panel" style={{ marginBottom: 16 }}><div className="panel-body"><div className="field-row dataset-upload-grid"><div className="field"><label>数据文件</label><input className="input" type="file" accept=".csv,.xlsx,.txt,.jsonl,.ndjson" onChange={event => setFile(event.target.files?.[0] || null)} /></div><div className="field"><label>数据集名称</label><input className="input" value={datasetName} placeholder={file?.name.replace(/\.[^.]+$/, '') || ''} onChange={event => setDatasetName(event.target.value)} /></div><button className="btn primary" style={{ alignSelf: 'end' }} disabled={!file || busy} onClick={() => void upload()}>{busy ? <Spinner /> : <Upload size={15} />}导入</button></div><div className="hint dataset-upload-hint">推荐 CSV；模板包含 text 和可选 gold_label，TXT 每行一条 text</div><div className="dataset-format-help"><strong>字段说明：</strong><code>text</code> 是待分类文本；<code>gold_label</code> 是可选的人工真实标签，用于评估和规则改进。模板中的 <code>gold_label</code> 可以留空。</div></div></div>
    <div className="split">
      <div className="panel">{datasets.length ? <div className="list">{datasets.map(item => <div className={`list-item dataset-list-item ${selectedId === item.id ? 'selected' : ''}`} key={item.id} onClick={() => setSelectedId(item.id)}><div><div className="list-title">{item.name}</div><div className="list-meta"><span>{item.item_count} Cases</span><span>{item.filename || '内置数据'}</span><span>{date(item.created_at)}</span></div></div><button className="btn icon danger" disabled={busy} onClick={event => { event.stopPropagation(); void removeDataset(item) }} title="删除数据集"><Trash2 size={15} /></button></div>)}</div> : <Empty icon={Database} title="暂无数据集" />}</div>
      <div className="stack">
        <div className="panel"><div className="panel-head"><h2>创建标注运行</h2></div><div className="panel-body"><div className="field-row"><div className="field"><label>当前数据集</label><select className="select" value={selectedId} onChange={event => setSelectedId(event.target.value)}><option value="">选择数据集</option>{datasets.map(item => <option key={item.id} value={item.id}>{item.name} · {item.item_count}</option>)}</select></div><div className="field"><label>Standard</label><select className="select" value={standardId} onChange={event => setStandardId(event.target.value)}><option value="">选择已激活版本</option>{standards.filter(item => item.status === 'active').map(item => <option key={item.id} value={item.id}>{item.name} v{item.version}</option>)}</select></div></div><div className="actions" style={{ marginTop: 14, justifyContent: 'flex-end' }}><button className="btn primary" disabled={!selectedId || !standardId || busy} onClick={() => void start()}>{busy ? <Spinner /> : <Play size={15} />}开始标注</button></div></div></div>
        <div className="panel"><div className="panel-head"><h2>数据预览</h2><span className="hint">内部 ID 已生成</span></div>{items.length ? <div className="table-wrap" style={{ maxHeight: 470 }}><table><thead><tr><th>ID</th><th>文本</th><th>Gold Label</th></tr></thead><tbody>{items.map(item => <tr key={item.id}><td><span className="rule-chip">{item.id.slice(0, 8)}</span></td><td className="text-cell">{item.text}</td><td>{item.gold_label || '-'}</td></tr>)}</tbody></table></div> : <Empty title="选择数据集查看内容" />}</div>
      </div>
    </div>
  </>
}

function RunsPage({ runs, refresh, notify }: { runs: Run[]; refresh: () => Promise<void>; notify: (text: string, error?: boolean) => void }) {
  const [selectedId, setSelectedId] = useState(runs[0]?.id || '')
  const [detail, setDetail] = useState<RunDetail | null>(null)
  const [filter, setFilter] = useState<Route | 'ALL'>('ALL')
  const [annotation, setAnnotation] = useState<Annotation | null>(null)
  const [reviewLabel, setReviewLabel] = useState('')
  const [reviewNote, setReviewNote] = useState('')
  const [compareIds, setCompareIds] = useState<[string, string]>(['', ''])
  const [comparison, setComparison] = useState<{ left: { run: Run; metrics: Metrics }; right: { run: Run; metrics: Metrics } } | null>(null)
  const [retrying, setRetrying] = useState(false)
  useEffect(() => { if (!selectedId && runs[0]) setSelectedId(runs[0].id) }, [runs, selectedId])
  const loadDetail = useCallback(async () => { if (selectedId) try { setDetail(await api.run(selectedId)) } catch (error) { notify(error instanceof Error ? error.message : '加载失败', true) } }, [selectedId, notify])
  useEffect(() => { void loadDetail() }, [loadDetail, runs])
  async function review() { if (!annotation || !reviewLabel) return; try { await api.review(annotation.id, reviewLabel, reviewNote); notify('人工审核已保存'); setAnnotation(null); await loadDetail() } catch (error) { notify(error instanceof Error ? error.message : '保存失败', true) } }
  async function compare() { if (!compareIds[0] || !compareIds[1]) return; try { setComparison(await api.compare(compareIds[0], compareIds[1])) } catch (error) { notify(error instanceof Error ? error.message : '对比失败', true) } }
  async function retry() { if (!detail || detail.run.status !== 'failed') return; setRetrying(true); try { await api.retryRun(detail.run.id); notify(`已从 ${detail.run.processed}/${detail.run.total} 继续运行`); await refresh(); await loadDetail() } catch (error) { notify(error instanceof Error ? error.message : '继续运行失败', true) } finally { setRetrying(false) } }
  const filtered = detail?.annotations.filter(item => filter === 'ALL' || item.route === filter) || []
  return <>
    <PageHead title="标注运行" meta={`${runs.length} 次运行`}>{detail?.run.status === 'completed' && <><a className="btn" href={`/api/runs/${detail.run.id}/export?format=csv`}><Upload size={15} style={{ transform: 'rotate(180deg)' }} />导出结果</a><a className="btn" href={`/api/runs/${detail.run.id}/export?format=jsonl&gold_only=true`}><ShieldCheck size={15} />导出 Gold</a></>}{detail?.run.status === 'failed' && <button className="btn primary" disabled={retrying} onClick={() => void retry()}>{retrying ? <Spinner /> : <Play size={15} />}继续运行</button>}<button className="btn" onClick={() => void refresh()}><RefreshCw size={15} />刷新</button></PageHead>
    <div className="split">
      <div className="panel">{runs.length ? <div className="list">{runs.map(run => <button key={run.id} className={`list-item ${selectedId === run.id ? 'selected' : ''}`} onClick={() => setSelectedId(run.id)}><div className="list-title">{run.dataset_name}</div><div className="list-meta"><Badge value={run.status} /><span>Standard v{run.standard_version}</span><span>{run.processed}/{run.total}</span></div>{run.status === 'running' && <div className="progress" style={{ marginTop: 9 }}><span style={{ width: `${run.total ? run.processed / run.total * 100 : 0}%` }} /></div>}{run.error && <div className="list-meta" style={{ color: 'var(--red)' }}>{run.error}</div>}</button>)}</div> : <Empty icon={ScanSearch} title="暂无运行" />}</div>
      <div className="stack">{detail ? <>
        <div className="four-col"><div className="metric"><div className="metric-label">自动通过率</div><div className="metric-value">{pct(detail.metrics.auto_accept_rate)}</div></div><div className="metric"><div className="metric-label">准确率</div><div className="metric-value">{pct(detail.metrics.accuracy)}</div><div className="metric-foot">n={detail.metrics.accuracy_sample_size}</div></div><div className="metric"><div className="metric-label">审核率</div><div className="metric-value">{pct(detail.metrics.review_rate)}</div></div><div className="metric"><div className="metric-label">冲突率</div><div className="metric-value">{pct(detail.metrics.rule_conflict_rate)}</div></div></div>
        <div className="panel"><div className="panel-head"><h2>标注结果</h2><select className="select" style={{ width: 155 }} value={filter} onChange={event => setFilter(event.target.value as Route | 'ALL')}><option value="ALL">全部路由</option>{['AUTO_ACCEPT', 'REVIEW', 'AMBIGUOUS', 'SPEC_GAP'].map(value => <option key={value}>{value}</option>)}</select></div>{filtered.length ? <div className="table-wrap" style={{ maxHeight: 620 }}><table><thead><tr><th>文本</th><th>Label</th><th>Rules</th><th>置信度</th><th>路由</th><th></th></tr></thead><tbody>{filtered.map(item => <tr key={item.id}><td className="text-cell">{item.text}</td><td>{item.human_label || item.label || '-'}</td><td><div className="rules">{item.rules_used.map(rule => <span className="rule-chip" key={rule}>{rule}</span>)}</div></td><td className="confidence">{item.confidence.toFixed(2)}</td><td><Badge value={item.route} /></td><td><button className="btn icon ghost" title="查看" onClick={() => { setAnnotation(item); setReviewLabel(item.human_label || item.label || ''); setReviewNote(item.review_note || '') }}><ChevronRight size={15} /></button></td></tr>)}</tbody></table></div> : <Empty title={detail.run.status === 'completed' ? '没有匹配的标注结果' : '运行处理中'} />}</div>
      </> : <Empty title="选择一次运行" />}</div>
    </div>
    {runs.filter(item => item.status === 'completed').length >= 2 && <div className="panel" style={{ marginTop: 16 }}><div className="panel-head"><h2>版本对比</h2><GitCompareArrows size={16} /></div><div className="panel-body"><div className="field-row" style={{ gridTemplateColumns: '1fr 1fr auto' }}><select className="select" value={compareIds[0]} onChange={event => setCompareIds([event.target.value, compareIds[1]])}><option value="">基准运行</option>{runs.filter(item => item.status === 'completed').map(item => <option key={item.id} value={item.id}>{item.dataset_name} · v{item.standard_version}</option>)}</select><select className="select" value={compareIds[1]} onChange={event => setCompareIds([compareIds[0], event.target.value])}><option value="">对比运行</option>{runs.filter(item => item.status === 'completed').map(item => <option key={item.id} value={item.id}>{item.dataset_name} · v{item.standard_version}</option>)}</select><button className="btn" onClick={() => void compare()} disabled={!compareIds[0] || !compareIds[1]}>对比</button></div>{comparison && <CompareView value={comparison} />}</div></div>}
    {annotation && <Modal title="标注详情" onClose={() => setAnnotation(null)} footer={<><button className="btn" onClick={() => setAnnotation(null)}>关闭</button><button className="btn primary" disabled={!reviewLabel} onClick={() => void review()}><Save size={14} />保存审核</button></>}>
      <dl className="detail-grid"><dt>文本</dt><dd>{annotation.text}</dd><dt>模型 Label</dt><dd>{annotation.label || '-'}</dd><dt>路由</dt><dd><Badge value={annotation.route} /></dd><dt>证据</dt><dd>{annotation.evidence}</dd><dt>Verifier</dt><dd><Badge value={annotation.verifier.verdict} /> {annotation.verifier.explanation}</dd><dt>路由原因</dt><dd>{annotation.route_reasons.join('；')}</dd><dt>Rules Used</dt><dd><div className="rules">{annotation.rules_used.map(rule => <span className="rule-chip" key={rule}>{rule}</span>)}</div></dd></dl>
      <div className="field"><label>人工 Label</label><input className="input" value={reviewLabel} onChange={event => setReviewLabel(event.target.value)} /></div><div className="field"><label>审核备注</label><textarea className="textarea" value={reviewNote} onChange={event => setReviewNote(event.target.value)} /></div>
    </Modal>}
  </>
}

function CompareView({ value }: { value: { left: { run: Run; metrics: Metrics }; right: { run: Run; metrics: Metrics } } }) {
  const rows: Array<[string, keyof Metrics]> = [['准确率', 'accuracy'], ['自动通过率', 'auto_accept_rate'], ['人工审核率', 'review_rate'], ['Rule 冲突率', 'rule_conflict_rate']]
  return <div className="compare-grid" style={{ marginTop: 16 }}><div className="compare-head">指标</div><div className="compare-head">Standard v{value.left.run.standard_version}</div><div className="compare-head">Standard v{value.right.run.standard_version}</div>{rows.map(([label, key]) => <FragmentRow key={key} label={label} left={value.left.metrics[key] as number | null} right={value.right.metrics[key] as number | null} invert={key === 'review_rate' || key === 'rule_conflict_rate'} />)}</div>
}
function FragmentRow({ label, left, right, invert }: { label: string; left: number | null; right: number | null; invert: boolean }) {
  const improved = left != null && right != null && (invert ? right < left : right > left)
  return <><div>{label}</div><div>{pct(left)}</div><div className={improved ? 'positive' : ''}>{pct(right)}</div></>
}

function GapsPage({ runs, standards, refresh, notify }: { runs: Run[]; standards: StandardSummary[]; refresh: () => Promise<void>; notify: (text: string, error?: boolean) => void }) {
  const completed = runs.filter(item => item.status === 'completed')
  const [runId, setRunId] = useState(completed[0]?.id || '')
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState<Suggestion | null>(null)
  const [ruleJson, setRuleJson] = useState('')
  const [reason, setReason] = useState('')
  useEffect(() => { void api.suggestions(runId || undefined).then(setSuggestions).catch(error => notify(error.message, true)) }, [runId, notify])
  async function mine() { if (!runId) return; setBusy(true); try { const result = await api.mine(runId); setSuggestions(result.suggestions); notify(result.suggestions.length ? `生成 ${result.suggestions.length} 条建议` : '没有达到聚类阈值的失败模式') } catch (error) { notify(error instanceof Error ? error.message : '挖掘失败', true) } finally { setBusy(false) } }
  function openEdit(item: Suggestion) {
    const run = runs.find(value => value.id === item.run_id); const standard = standards.find(value => value.id === run?.standard_id); const id = item.payload.target_rule_id
    const allRules = standard ? [...standard.compiled.definition_rules, ...standard.compiled.decision_rules.boundary_rules, ...standard.compiled.decision_rules.priority_rules] : []
    const rule = allRules.find(value => value.rule_id === id)
    if (!run || !standard || !id || !rule) { notify('建议未定位到可修改的现有 Rule', true); return }
    setEditing(item); setRuleJson(JSON.stringify(rule, null, 2)); setReason(item.payload.proposed_change)
  }
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
  return <>
    <PageHead title="规则改进" meta={`${suggestions.length} 条修改建议`}><select className="select" style={{ width: 260 }} value={runId} onChange={event => setRunId(event.target.value)}><option value="">选择已完成运行</option>{completed.map(run => <option key={run.id} value={run.id}>{run.dataset_name} · Standard v{run.standard_version}</option>)}</select><button className="btn primary" disabled={!runId || busy} onClick={() => void mine()}>{busy ? <Spinner /> : <Sparkles size={15} />}挖掘 Spec Gap</button></PageHead>
    <div className="panel">{suggestions.length ? suggestions.map(item => <div className="suggestion" key={item.id}><div className="actions" style={{ justifyContent: 'space-between' }}><div><h3>{item.payload.title}</h3><div className="list-meta"><Badge value={item.status} />{item.payload.labels.map(label => <span key={label}>{label}</span>)}{item.payload.target_rule_id && <span className="rule-chip">{item.payload.target_rule_id}</span>}</div></div><button className="btn" onClick={() => openEdit(item)}>修改 Rule <ArrowRight size={14} /></button></div><p><b>问题：</b>{item.payload.problem}</p><p><b>建议：</b>{item.payload.proposed_change}</p><ul className="case-list">{item.payload.typical_cases.map(value => <li key={value}>{value}</li>)}</ul></div>) : <Empty icon={Lightbulb} title="暂无 Rule 修改建议" />}</div>
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
      {([['compiler_model', '标准编译模型'], ['annotator_model', '标注模型'], ['verifier_model', '校验模型'], ['miner_model', 'Spec Gap 模型'], ['embedding_model', 'Embedding 模型']] as Array<[keyof ModelSettings, string]>).map(([key, label]) => <div className="field" key={key}><label>{label}</label><input className="input" list="qianfan-models" value={String(settings[key])} onChange={event => update(key, event.target.value)} /></div>)}
    </div><div className="two-col"><div className="field"><label>AUTO_ACCEPT 置信度阈值</label><input className="input" type="number" min="0" max="1" step="0.01" value={settings.auto_accept_threshold} onChange={event => update('auto_accept_threshold', Number(event.target.value))} /></div><div className="field"><label>Spec Gap 最小重复数</label><input className="input" type="number" min="2" step="1" value={settings.spec_gap_min_cluster_size} onChange={event => update('spec_gap_min_cluster_size', Number(event.target.value))} /></div></div></div></div>}
  </>
}
