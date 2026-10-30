import { useEffect, useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useApi } from '../hooks/useApi.js'
import { benchmarksApi } from '../api/services.js'
import { errorMessage } from '../api/client.js'
import { Async, Badge, Card, EmptyState, ErrorState, Field, Loading, Notice, PageHeader, Table, fmtDate } from '../components/ui.jsx'

const TONE = { queued: 'neutral', running: 'info', completed: 'ok', failed: 'bad' }
const f = (v, d = 3) => (typeof v === 'number' ? v.toFixed(d) : '—')
const sci = (v) => (typeof v === 'number' ? v.toExponential(2) : '—')
const StatusBadge = ({ s }) => <Badge tone={TONE[s] || 'neutral'}>{s}</Badge>
const LARGE = 1_000_000
const ACTIVE = (s) => s === 'queued' || s === 'running'

function StartPanel({ onStarted }) {
  const [form, setForm] = useState({ rows: 100000, trials: 5, warmup: 1 })
  const [pre, setPre] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const set = (k) => (e) => setForm((s) => ({ ...s, [k]: Number(e.target.value) }))

  const review = async () => {
    setErr(null); setBusy(true)
    try { setPre(await benchmarksApi.preflight(form.rows)) } catch (e) { setErr(errorMessage(e)) } finally { setBusy(false) }
  }
  const start = async () => {
    setErr(null); setBusy(true)
    try {
      const s = await benchmarksApi.start({ ...form, confirm: form.rows >= LARGE })
      setPre(null); onStarted(s)
    } catch (e) { setErr(errorMessage(e)) } finally { setBusy(false) }
  }

  return (
    <Card title="Run a new benchmark" subtitle="Generates SYNTHETIC data, then runs the same workload in Pandas and in PySpark (local mode)">
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Rows" htmlFor="b-rows">
          <select id="b-rows" className="input w-full" value={form.rows} onChange={(e) => { set('rows')(e); setPre(null) }}>
            <option value={10000}>10,000 (quick check)</option>
            <option value={100000}>100,000</option>
            <option value={1000000}>1,000,000 (needs confirmation)</option>
            <option value={5000000}>5,000,000 (needs confirmation)</option>
          </select>
        </Field>
        <Field label="Measured trials" htmlFor="b-trials">
          <input id="b-trials" type="number" min={1} max={30} className="input w-full" value={form.trials} onChange={set('trials')} />
        </Field>
        <Field label="Warm-up runs" htmlFor="b-warm">
          <input id="b-warm" type="number" min={0} max={5} className="input w-full" value={form.warmup} onChange={set('warmup')} />
        </Field>
      </div>
      {err && <div className="mt-3"><Notice tone="warn">{err}</Notice></div>}
      {!pre ? (
        <button className="btn btn-primary mt-3" onClick={review} disabled={busy}>{busy ? 'Checking…' : 'Review & start…'}</button>
      ) : (
        <div className="mt-3 space-y-2 rounded-md border border-navy-600 p-3 text-sm" role="alertdialog" aria-label="Confirm benchmark">
          <p className="font-medium">Confirm this benchmark</p>
          <ul className="list-disc pl-5 text-xs text-slate-300">
            <li>{pre.rows.toLocaleString()} synthetic rows, {form.warmup} warm-up + {form.trials} measured trial(s) per framework</li>
            <li>Estimated peak memory ≈ {Math.round(pre.estimated_peak_mb).toLocaleString()} MB (heuristic) of {Math.round(pre.available_mb ?? 0).toLocaleString()} MB available</li>
            <li>Estimated temporary disk ≈ {Math.round(pre.estimated_disk_mb).toLocaleString()} MB (removed afterwards)</li>
            <li>PySpark: {pre.spark.available ? `available (PySpark ${pre.spark.pyspark}, Java ${pre.spark.java?.major ?? '?'})` : 'NOT available'}</li>
          </ul>
          {!pre.spark.available && <Notice tone="warn">{(pre.spark.reasons || []).join(' ')} Pandas will still be measured; the run will be recorded as failed. Pandas is never substituted for Spark.</Notice>}
          {!pre.memory_ok && <Notice tone="warn">Not enough free memory for this size. The server will refuse it.</Notice>}
          {pre.requires_confirmation && <Notice tone="warn">This is a large run and may take several minutes and use a lot of memory.</Notice>}
          <div className="flex gap-2">
            <button className="btn btn-primary" onClick={start} disabled={busy || !pre.memory_ok}>{busy ? 'Starting…' : 'Start benchmark'}</button>
            <button className="btn" onClick={() => setPre(null)} disabled={busy}>Cancel</button>
          </div>
        </div>
      )}
    </Card>
  )
}

function SuiteDetail({ id, onChanged }) {
  const state = useApi(() => benchmarksApi.get(id), [id])
  const [err, setErr] = useState(null)
  const s = state.data

  // Poll only while this benchmark is queued/running.
  useEffect(() => {
    if (!s || !ACTIVE(s.status)) return undefined
    const t = setInterval(() => { state.reload(); onChanged() }, 3000)
    return () => clearInterval(t)
  }, [s?.status, id]) // eslint-disable-line react-hooks/exhaustive-deps

  if (state.loading && !s) return <Loading />
  if (state.error && !s) return <ErrorState message={state.error} onRetry={state.reload} />
  const runs = s.runs ?? []
  const pandas = runs.find((r) => r.framework === 'pandas')
  const spark = runs.find((r) => r.framework === 'spark')
  const cmp = s.comparison
  const cancel = async () => { try { await benchmarksApi.cancel(id); state.reload(); onChanged() } catch (e) { setErr(errorMessage(e)) } }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold">Benchmark #{s.id}</h3><StatusBadge s={s.status} />
        <Badge tone="neutral">synthetic data</Badge>
        {ACTIVE(s.status) && <button className="btn ml-auto" onClick={cancel}>Cancel</button>}
      </div>
      {err && <Notice tone="warn">{err}</Notice>}
      {s.error_details && <Notice tone="warn">{s.error_details}</Notice>}
      {ACTIVE(s.status) && <Notice>This benchmark is {s.status}. Results appear when it finishes; nothing is shown until measured.</Notice>}
      <dl className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        <div><dt className="label">Rows (actual)</dt><dd>{s.input_rows?.toLocaleString() ?? '—'}</dd></div>
        <div><dt className="label">Trials / warm-up</dt><dd>{s.trials} / {s.warmup}</dd></div>
        <div><dt className="label">Data generation (s)</dt><dd>{f(s.data_generation_s)}</dd></div>
        <div><dt className="label">Speedup (Pandas ÷ Spark)</dt><dd>{f(s.speedup)}{typeof s.speedup === 'number' ? (s.speedup > 1 ? ' · Spark faster' : ' · Pandas faster') : ''}</dd></div>
        <div><dt className="label">Numerical agreement</dt><dd>{cmp ? (cmp.passed ? 'PASS' : 'FAIL') : '—'}</dd></div>
        <div><dt className="label">Mean abs error</dt><dd>{sci(cmp?.mae)}</dd></div>
        <div><dt className="label">Max abs error</dt><dd>{sci(cmp?.max_abs_err)}</dd></div>
        <div><dt className="label">Started</dt><dd>{fmtDate(s.started_at)}</dd></div>
      </dl>
      {runs.length > 0 && (
        <Table rows={runs} rowKey={(r) => r.id} columns={[
          { key: 'framework', label: 'Framework', render: (r) => <>{r.framework === 'spark' ? 'PySpark' : 'Pandas'} <StatusBadge s={r.status} /></> },
          { key: 'median_s', label: 'Median s', render: (r) => f(r.median_s) },
          { key: 'spread', label: 'Min–max s', render: (r) => (r.min_s != null ? `${f(r.min_s)} – ${f(r.max_s)}` : '—') },
          { key: 'trials', label: 'Trials (s)', render: (r) => (r.trial_durations ? r.trial_durations.map((x) => x.toFixed(3)).join(', ') : '—') },
          { key: 'init_s', label: 'Init s', render: (r) => f(r.init_s, 2) },
          { key: 'throughput', label: 'Rows/s', render: (r) => f(r.throughput, 0) },
          { key: 'peak_rss_mb', label: 'Peak RSS MB*', render: (r) => f(r.peak_rss_mb, 0) },
          { key: 'valid_rows', label: 'Valid rows', render: (r) => r.valid_rows?.toLocaleString() ?? '—' },
          { key: 'output_rows', label: 'Output rows', render: (r) => r.output_rows?.toLocaleString() ?? '—' },
        ]} />
      )}
      {runs.some((r) => r.status === 'failed' && r.error_details) && runs.filter((r) => r.status === 'failed').map((r) => (
        <Notice key={r.id} tone="warn">{r.framework === 'spark' ? 'PySpark' : 'Pandas'} failed: {r.error_details}</Notice>
      ))}
      <details className="text-xs text-slate-300">
        <summary className="cursor-pointer">Timing scope &amp; environment</summary>
        <p className="mt-2">{pandas?.timing_scope || spark?.timing_scope}</p>
        <p className="mt-1">*Peak RSS is a sampled approximation of the worker process tree (includes the Spark JVM).</p>
        <pre className="mt-2 overflow-x-auto rounded bg-navy-900 p-2">{JSON.stringify(s.environment, null, 2)}</pre>
        <pre className="mt-2 overflow-x-auto rounded bg-navy-900 p-2">{JSON.stringify(s.config, null, 2)}</pre>
      </details>
    </div>
  )
}

export default function Benchmarks() {
  const state = useApi(() => benchmarksApi.list())
  const [sel, setSel] = useState(null)
  const suites = state.data?.suites ?? []
  const items = state.data?.items ?? []

  // Chart data come only from completed, measured runs returned by the API.
  const bySize = useMemo(() => {
    const m = {}
    items.forEach((r) => {
      if (r.status !== 'completed' || typeof r.median_s !== 'number') return
      const k = `${r.records}`
      m[k] = m[k] || { records: r.records, n: 0 }
      m[k][r.engine] = r.median_s // latest run per size/framework wins (items are ordered by id)
    })
    return Object.values(m).sort((a, b) => a.records - b.records)
  }, [items])
  const speedups = suites.filter((s) => typeof s.speedup === 'number').sort((a, b) => a.requested_rows - b.requested_rows)
    .map((s) => ({ label: `#${s.id} · ${s.input_rows?.toLocaleString()}`, speedup: s.speedup }))
  const active = suites.some((s) => ACTIVE(s.status))

  useEffect(() => {
    if (!active) return undefined
    const t = setInterval(state.reload, 4000)
    return () => clearInterval(t)
  }, [active]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <PageHeader title="Big Data Benchmarks"
        description="Pandas vs PySpark (local mode, one machine) on SYNTHETIC data. Only values measured by the backend are shown." />
      <div className="space-y-4">
        <StartPanel onStarted={(s) => { setSel(s.id); state.reload() }} />
        <Async state={state}>
          {(d) => suites.length === 0 ? (
            <Card><EmptyState title="No benchmarks have been run yet" text={d.note || 'Start one above; results will be listed here.'} /></Card>
          ) : (
            <>
              <div className="grid gap-4 xl:grid-cols-2">
                <Card title="Median processing time by dataset size" subtitle="Seconds; lower is faster. Read → process → write Parquet; excludes data generation, framework start-up and warm-up">
                  <div className="h-72" role="img" aria-label="Median runtime by dataset size">
                    <ResponsiveContainer>
                      <BarChart data={bySize}>
                        <CartesianGrid stroke="#1e2d44" strokeDasharray="3 3" />
                        <XAxis dataKey="records" stroke="#94a3b8" fontSize={11} tickFormatter={(v) => v.toLocaleString()} />
                        <YAxis stroke="#94a3b8" fontSize={11} />
                        <Tooltip contentStyle={{ background: '#0f1b2d', border: '1px solid #1e2d44' }} />
                        <Legend />
                        <Bar dataKey="pandas" name="Pandas" fill="#22d3ee" />
                        <Bar dataKey="spark" name="PySpark" fill="#14b8a6" />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </Card>
                <Card title="Speedup per benchmark (Pandas ÷ PySpark)" subtitle="Above 1: PySpark faster. Below 1: Pandas faster. Only benchmarks whose outputs agreed are plotted">
                  {speedups.length === 0 ? <EmptyState title="No verified speedup yet" text="A speedup is shown only when both frameworks completed and agreed numerically." /> : (
                    <div className="h-72" role="img" aria-label="Speedup per benchmark">
                      <ResponsiveContainer>
                        <LineChart data={speedups}>
                          <CartesianGrid stroke="#1e2d44" strokeDasharray="3 3" />
                          <XAxis dataKey="label" stroke="#94a3b8" fontSize={11} />
                          <YAxis stroke="#94a3b8" fontSize={11} />
                          <Tooltip contentStyle={{ background: '#0f1b2d', border: '1px solid #1e2d44' }} />
                          <Line type="monotone" dataKey="speedup" name="Speedup" stroke="#22d3ee" dot />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  )}
                </Card>
              </div>
              <Card title="Benchmark history" subtitle="Click a row for trial-level detail">
                <Table rows={suites} rowKey={(r) => r.id} onRowClick={(r) => setSel(r.id)} selectedKey={sel} columns={[
                  { key: 'id', label: '#' },
                  { key: 'status', label: 'Status', render: (r) => <StatusBadge s={r.status} /> },
                  { key: 'requested_rows', label: 'Rows', render: (r) => (r.input_rows ?? r.requested_rows).toLocaleString() },
                  { key: 'trials', label: 'Trials', render: (r) => `${r.trials} (+${r.warmup} warm-up)` },
                  { key: 'speedup', label: 'Speedup', render: (r) => f(r.speedup) },
                  { key: 'agree', label: 'Agreement', render: (r) => (r.comparison ? (r.comparison.passed ? 'PASS' : 'FAIL') : '—') },
                  { key: 'created_at', label: 'Created', render: (r) => fmtDate(r.created_at) },
                ]} />
                <div className="mt-3"><Notice>Synthetic benchmarks measure speed only; they say nothing about environmental results. Local-mode Spark on one machine does not represent cluster performance, and results depend on this hardware, dataset size and workload.</Notice></div>
              </Card>
              {sel && <Card title="Benchmark detail"><SuiteDetail id={sel} onChanged={state.reload} /></Card>}
            </>
          )}
        </Async>
      </div>
    </>
  )
}
