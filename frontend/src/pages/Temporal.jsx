import { useMemo, useState } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ArrowRight } from 'lucide-react'
import { useApi } from '../hooks/useApi.js'
import { analyticsApi, regionsApi } from '../api/services.js'
import { Async, Card, EmptyState, Field, INDEX_INFO, Notice, PageHeader } from '../components/ui.jsx'

const num = (p) => {
  const v = p.value ?? p.mean
  return typeof v === 'number' ? v : null
}

function nearest(points, date) {
  if (!date || !points.length) return null
  const t = new Date(date).getTime()
  return points.reduce((best, p) => (best === null || Math.abs(new Date(p.date) - t) < Math.abs(new Date(best.date) - t) ? p : best), null)
}

export default function Temporal() {
  const regions = useApi(() => regionsApi.list())
  const [region, setRegion] = useState('')
  const [index, setIndex] = useState('ndvi')
  const [earlier, setEarlier] = useState('')
  const [later, setLater] = useState('')
  const [synthetic, setSynthetic] = useState(false)
  const series = useApi(() => analyticsApi.temporal({ index, ...(region ? { region } : {}), ...(synthetic ? { include_synthetic: true } : {}) }), [index, region, synthetic])
  const info = INDEX_INFO[index]

  const pts = useMemo(() => (series.data?.points ?? []).filter((p) => p.date && num(p) !== null).map((p) => ({ ...p, v: num(p) })), [series.data])
  const a = nearest(pts, earlier)
  const b = nearest(pts, later)
  const delta = a && b ? b.v - a.v : null

  return (
    <>
      <PageHeader title="Temporal Change Analysis" description="Compare an index between two observation dates. Differences are changes in index values, not proof of land-cover change." />
      <Card title="Selection" className="mb-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Field label="Region" htmlFor="t-region">
            <select id="t-region" className="input" value={region} onChange={(e) => setRegion(e.target.value)}>
              <option value="">All regions</option>
              {(regions.data?.items ?? []).map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select>
          </Field>
          <Field label="Index" htmlFor="t-index">
            <select id="t-index" className="input" value={index} onChange={(e) => setIndex(e.target.value)}>
              {Object.entries(INDEX_INFO).map(([k, v]) => <option key={k} value={k}>{v.label} — {v.name}</option>)}
            </select>
          </Field>
          <Field label="Earlier observation" htmlFor="t-a"><input id="t-a" type="date" className="input" value={earlier} onChange={(e) => setEarlier(e.target.value)} /></Field>
          <Field label="Later observation" htmlFor="t-b"><input id="t-b" type="date" className="input" value={later} onChange={(e) => setLater(e.target.value)} /></Field>
        </div>
        <label className="mt-3 flex items-center gap-2 text-xs text-slate-300">
          <input type="checkbox" checked={synthetic} onChange={(e) => setSynthetic(e.target.checked)} />
          Include synthetic test fixtures (generated rasters used for testing; never real satellite observations)
        </label>
        {synthetic && <div className="mt-2"><Notice tone="warn">SYNTHETIC test data may be included below. It is not Sentinel-2 imagery and must not be interpreted as an environmental finding.</Notice></div>}
      </Card>

      <Async state={series}>
        {(d) => (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
            <Card title={`${info.label} time series`} subtitle={d.region ? `Region: ${d.region}` : 'All regions'} className="xl:col-span-2">
              {!d.available || pts.length === 0 ? (
                <EmptyState title="Observations unavailable" text={d.reason || 'No temporal results exist for this selection.'} />
              ) : (
                <div className="h-72" role="img" aria-label={`${info.label} time series chart`}>
                  <ResponsiveContainer>
                    <LineChart data={pts} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
                      <CartesianGrid stroke="#1e2d44" strokeDasharray="3 3" />
                      <XAxis dataKey="date" stroke="#94a3b8" fontSize={11} />
                      <YAxis domain={[-1, 1]} stroke="#94a3b8" fontSize={11} />
                      <Tooltip contentStyle={{ background: '#0f1b2d', border: '1px solid #1e2d44' }} />
                      <Line type="monotone" dataKey="v" name={info.label} stroke={info.color} dot={{ r: 2 }} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Card>

            <Card title="Before / after">
              <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 text-center">
                <div className="rounded-md border border-navy-600 bg-navy-900 p-3">
                  <div className="label">Earlier</div>
                  <div className="mt-1 text-lg font-semibold tabular-nums">{a ? a.v.toFixed(3) : '—'}</div>
                  <div className="text-[11px] text-slate-500">{a ? a.date : earlier || 'not selected'}</div>
                </div>
                <ArrowRight size={16} className="text-slate-500" aria-hidden="true" />
                <div className="rounded-md border border-navy-600 bg-navy-900 p-3">
                  <div className="label">Later</div>
                  <div className="mt-1 text-lg font-semibold tabular-nums">{b ? b.v.toFixed(3) : '—'}</div>
                  <div className="text-[11px] text-slate-500">{b ? b.date : later || 'not selected'}</div>
                </div>
              </div>
              <div className="mt-4">
                <div className="label">Change (Δ{info.label})</div>
                <div className="mt-1 text-2xl font-semibold tabular-nums text-white">{delta === null ? '—' : `${delta >= 0 ? '+' : ''}${delta.toFixed(3)}`}</div>
              </div>
              <div className="mt-3">
                {delta === null
                  ? <Notice>Select two dates with available observations to compute a change.</Notice>
                  : <Notice tone="warn">A change in {info.label} can also come from season, cloud contamination or sensor effects. Verify before drawing land-cover conclusions.</Notice>}
              </div>
            </Card>
          </div>
        )}
      </Async>
    </>
  )
}
