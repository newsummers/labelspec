import { useCallback, useEffect, useState, type ReactNode } from 'react'
import {
  AlertTriangle, ArrowRight, BarChart3, Check, ChevronRight, CircleGauge, Database,
  FileCode2, FlaskConical, GitCompareArrows, Layers3, Lightbulb, LoaderCircle,
  Play, Plus, RefreshCw, Save, ScanSearch, Settings, ShieldCheck, Sparkles,
  Upload, X,
} from 'lucide-react'
import { api } from './api'
import type {
  Annotation, Dataset, Metrics, ModelSettings, Route, Run, RunDetail, StandardSummary,
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
function Modal({ title, children, footer, onClose }: { title: string; children: ReactNode; footer?: ReactNode; onClose: () => void }) {
  return <div className="modal-backdrop" onMouseDown={onClose}><div className="modal" onMouseDown={event => event.stopPropagation()}>
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
      <div className="brand"><span className="brand-mark"><Layers3 size={17} /></span><span>LabelSpec</span><span className="version">v0.1</span></div>
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

function StandardsPage({ standards, refresh, notify }: { standards: StandardSummary[]; refresh: () => Promise<void>; notify: (text: string, error?: boolean) => void }) {
  const [selectedId, setSelectedId] = useState(standards[0]?.id || '')
  const [detail, setDetail] = useState<StandardSummary | null>(null)
  const [tab, setTab] = useState<'definitions' | 'decisions' | 'yaml'>('definitions')
  const [compileOpen, setCompileOpen] = useState(false)
  const [name, setName] = useState('客户咨询意图分类标准')
  const [source, setSource] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (!selectedId && standards[0]) setSelectedId(standards[0].id) }, [standards, selectedId])
  useEffect(() => { if (selectedId) void api.standard(selectedId).then(setDetail).catch(error => notify(error.message, true)) }, [selectedId, notify])

  async function loadDemo(kind: 'demo' | 'template') {
    try { const data = await api.demo(); setSource(kind === 'demo' ? data.standard_markdown : data.standard_template); setCompileOpen(true) }
    catch (error) { notify(error instanceof Error ? error.message : '加载失败', true) }
  }
  async function runCompile() {
    setBusy(true)
    try { const result = await api.compile(name, source); notify(result.validation.valid ? '标准已编译并通过校验' : '标准已编译，但校验未通过', !result.validation.valid); setCompileOpen(false); await refresh(); setSelectedId(result.standard.id) }
    catch (error) { notify(error instanceof Error ? error.message : '编译失败', true) }
    finally { setBusy(false) }
  }
  async function activate() {
    if (!detail) return
    setBusy(true); try { await api.activate(detail.id); notify(`Standard v${detail.version} 已激活`); await refresh(); setDetail(await api.standard(detail.id)) } catch (error) { notify(error instanceof Error ? error.message : '激活失败', true) } finally { setBusy(false) }
  }
  const decisions = detail?.compiled.decision_rules
  return <>
    <PageHead title="标准管理" meta={`${standards.length} 个版本`}><button className="btn" onClick={() => void loadDemo('template')}><FileCode2 size={15} />标准模板</button><button className="btn" onClick={() => void loadDemo('demo')}><FlaskConical size={15} />演示标准</button><button className="btn primary" onClick={() => setCompileOpen(true)}><Plus size={15} />编译标准</button></PageHead>
    <div className="split">
      <div className="panel">{standards.length ? <div className="list">{standards.map(item => <button key={item.id} className={`list-item ${selectedId === item.id ? 'selected' : ''}`} onClick={() => setSelectedId(item.id)}><div className="list-title">{item.name} v{item.version}</div><div className="list-meta"><Badge value={item.status} /><span>{item.counts.labels} Labels</span><span>{item.counts.definitions + item.counts.boundaries + item.counts.priorities} Rules</span></div>{item.change_summary && <div className="list-meta">{item.change_summary}</div>}</button>)}</div> : <Empty icon={FileCode2} title="暂无标准" />}</div>
      <div className="panel">{detail ? <>
        <div className="panel-head"><div><h2>{detail.name} · v{detail.version}</h2><div className="list-meta"><Badge value={detail.status} /><span>{detail.validation?.valid ? '校验通过' : '校验失败'}</span><span>{date(detail.created_at)}</span></div></div>{detail.status === 'draft' && <button className="btn primary" disabled={busy || !detail.validation?.valid} onClick={() => void activate()}>{busy ? <Spinner /> : <Check size={14} />}激活</button>}</div>
        <div className="tabs"><button className={`tab ${tab === 'definitions' ? 'active' : ''}`} onClick={() => setTab('definitions')}>Definition</button><button className={`tab ${tab === 'decisions' ? 'active' : ''}`} onClick={() => setTab('decisions')}>Boundary & Priority</button><button className={`tab ${tab === 'yaml' ? 'active' : ''}`} onClick={() => setTab('yaml')}>YAML</button></div>
        <div className={tab === 'yaml' ? '' : 'panel-body'}>
          {tab === 'definitions' && detail.compiled.definition_rules.map(rule => { const stat = detail.rule_stats?.find(item => item.rule_id === rule.rule_id); return <div className="rule-block" key={rule.rule_id}><div className="rule-title"><span className="rule-chip">{rule.rule_id}</span>{rule.label}</div>{stat && <div className="list-meta"><span>使用 {stat.uses}</span><span>冲突 {stat.conflicts}</span><span>Override {stat.overrides}</span><span>修改 {stat.modifications}</span></div>}<div className="rule-copy">{rule.definition}</div><div className="rule-lists"><div className="rule-list"><strong>Include</strong>{rule.include.map(item => <div key={item}>+ {item}</div>)}</div><div className="rule-list"><strong>Exclude</strong>{rule.exclude.map(item => <div key={item}>- {item}</div>)}</div></div></div> })}
          {tab === 'decisions' && <>{decisions?.boundary_rules.map(rule => <div className="rule-block" key={rule.rule_id}><div className="rule-title"><span className="rule-chip">{rule.rule_id}</span>{rule.labels.join(' ↔ ')}</div><div className="rule-copy"><b>触发条件：</b>{rule.condition}<br /><br /><b>决策：</b>{rule.decision}</div></div>)}{decisions?.priority_rules.map(rule => <div className="rule-block" key={rule.rule_id}><div className="rule-title"><span className="rule-chip">{rule.rule_id}</span>Priority</div><div className="rule-copy">{rule.principle}</div></div>)}</>}
          {tab === 'yaml' && <pre className="code">{Object.entries(detail.files || {}).map(([filename, content]) => `# ${filename}\n${content}`).join('\n')}</pre>}
        </div>
      </> : <Empty title="选择一个标准版本" />}</div>
    </div>
    {compileOpen && <Modal title="编译业务标准" onClose={() => !busy && setCompileOpen(false)} footer={<><button className="btn" disabled={busy} onClick={() => setCompileOpen(false)}>取消</button><button className="btn primary" disabled={busy || source.trim().length < 20 || !name.trim()} onClick={() => void runCompile()}>{busy ? <Spinner /> : <Sparkles size={15} />}编译</button></>}>
      <div className="field"><label>标准名称</label><input className="input" value={name} onChange={event => setName(event.target.value)} /></div><div className="field"><label>standard.md</label><textarea className="textarea editor" value={source} onChange={event => setSource(event.target.value)} /></div>
    </Modal>}
  </>
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
  async function start() { if (!selectedId || !standardId) return; setBusy(true); try { await api.createRun(selectedId, standardId); notify('标注运行已创建'); await refresh(); setPage('runs') } catch (error) { notify(error instanceof Error ? error.message : '创建运行失败', true) } finally { setBusy(false) } }
  return <>
    <PageHead title="数据集" meta={`${datasets.reduce((sum, item) => sum + item.item_count, 0)} 条数据`}><button className="btn" disabled={busy} onClick={() => void demo()}><FlaskConical size={15} />导入演示数据</button></PageHead>
    <div className="panel" style={{ marginBottom: 16 }}><div className="panel-body"><div className="field-row" style={{ gridTemplateColumns: '1fr 1fr auto' }}><div className="field"><label>CSV / JSONL</label><input className="input" type="file" accept=".csv,.jsonl,.ndjson" onChange={event => setFile(event.target.files?.[0] || null)} /></div><div className="field"><label>数据集名称</label><input className="input" value={datasetName} placeholder={file?.name.replace(/\.[^.]+$/, '') || ''} onChange={event => setDatasetName(event.target.value)} /></div><button className="btn primary" style={{ alignSelf: 'end' }} disabled={!file || busy} onClick={() => void upload()}>{busy ? <Spinner /> : <Upload size={15} />}导入</button></div></div></div>
    <div className="split">
      <div className="panel">{datasets.length ? <div className="list">{datasets.map(item => <button key={item.id} className={`list-item ${selectedId === item.id ? 'selected' : ''}`} onClick={() => setSelectedId(item.id)}><div className="list-title">{item.name}</div><div className="list-meta"><span>{item.item_count} Cases</span><span>{item.filename || '内置数据'}</span><span>{date(item.created_at)}</span></div></button>)}</div> : <Empty icon={Database} title="暂无数据集" />}</div>
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
