import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { MapContainer, Rectangle, TileLayer } from 'react-leaflet'
import { useApi } from '../hooks/useApi.js'
import { analyticsApi, regionsApi } from '../api/services.js'
import { Async, Badge, Card, EmptyState, Field, INDEX_INFO, Notice, PageHeader, Table } from '../components/ui.jsx'

export default function Regional() {
  const regions = useApi(() => regionsApi.list())
  const [synthetic, setSynthetic] = useState(false)
  const summary = useApi(() => analyticsApi.regional(synthetic ? { include_synthetic: true } : {}), [synthetic])
  const [sel, setSel] = useState('')
  const items = regions.data?.items ?? []
  const selected = items.find((r) => r.id === sel) || null

  return (
    <>
      <PageHeader title="Regional Analytics" description="Indicator summaries and regional comparisons. A region is 'configured' when metadata exists and 'analysed' only when real results exist." />
      <Async state={regions}>
        {() => (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
            <Card title="Regions" className="xl:col-span-2">
              <Table
                rows={items}
                rowKey={(r) => r.id}
                selectedKey={sel}
                onRowClick={(r) => setSel(r.id)}
                columns={[
                  { key: 'name', label: 'Region' },
                  { key: 'state', label: 'State' },
                  { key: 'configured', label: 'Configured', render: (r) => <Badge tone="info">{r.configured ? 'Yes' : 'No'}</Badge> },
                  { key: 'analysed', label: 'Analysed', render: (r) => <Badge tone={r.analysed ? 'ok' : 'neutral'}>{r.analysed ? 'Yes' : 'No'}</Badge> },
                ]}
              />
            </Card>

            <Card title="Geographic context">
              <Field label="Region" htmlFor="rg"><select id="rg" className="input" value={sel} onChange={(e) => setSel(e.target.value)}>
                <option value="">Select a region</option>{items.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}</select></Field>
              <div className="mt-3 h-52 overflow-hidden rounded-md border border-navy-600">
                {selected ? (
                  <MapContainer key={selected.id} bounds={[[selected.bbox[1], selected.bbox[0]], [selected.bbox[3], selected.bbox[2]]]} className="h-full w-full" scrollWheelZoom={false}>
                    <TileLayer url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" attribution='&copy; OpenStreetMap contributors' />
                    <Rectangle bounds={[[selected.bbox[1], selected.bbox[0]], [selected.bbox[3], selected.bbox[2]]]} pathOptions={{ color: '#22d3ee', weight: 2, fillOpacity: 0.1 }} />
                  </MapContainer>
                ) : <EmptyState title="No region selected" />}
              </div>
              {selected && <p className="mt-2 font-mono text-[11px] text-slate-400">bbox: {selected.bbox.join(', ')}</p>}
            </Card>

            <Card title="Indicator summaries" subtitle={selected ? selected.name : 'All regions with results'} className="xl:col-span-3">
              <label className="mb-3 flex items-center gap-2 text-xs text-slate-300">
                <input type="checkbox" checked={synthetic} onChange={(e) => setSynthetic(e.target.checked)} />
                Include synthetic test fixtures (generated rasters used for testing; never real satellite observations)
              </label>
              <Async state={summary}>
                {(s) => {
                  const rows = (s.items ?? []).filter((x) => !selected || x.region === selected.id)
                  if (!s.available || rows.length === 0) return (
                    <div className="space-y-3">
                      <div className="grid gap-3 sm:grid-cols-3">
                        {Object.entries(INDEX_INFO).map(([k, v]) => (
                          <div key={k} className="rounded-md border border-navy-600 bg-navy-900 p-3">
                            <div className="text-sm font-semibold" style={{ color: v.color }}>{v.label}</div>
                            <div className="mt-1 text-lg tabular-nums text-slate-500">—</div>
                            <div className="text-xs text-slate-500">mean · SD · coverage unavailable</div>
                          </div>
                        ))}
                      </div>
                      <Notice>{s.available ? 'No results for the selected region.' : (s.reason || 'No analysis has been run yet.')}</Notice>
                    </div>
                  )
                  const chart = rows.map((x) => ({ name: `${x.region} · ${x.index.toUpperCase()}`, mean: x.latest_mean }))
                  return (
                    <div className="space-y-3">
                      {s.includes_synthetic && <Notice tone="warn">Synthetic test fixtures may be included. They are not Sentinel-2 observations.</Notice>}
                      <Table rows={rows} rowKey={(x) => `${x.region}-${x.index}`} columns={[
                        { key: 'region', label: 'Region', render: (x) => <>{x.region} {x.synthetic_fixture && <Badge tone="warn">synthetic</Badge>}</> },
                        { key: 'index', label: 'Index', render: (x) => x.index.toUpperCase() },
                        { key: 'observations', label: 'Obs.' },
                        { key: 'last_date', label: 'Latest date' },
                        { key: 'latest_mean', label: 'Mean', render: (x) => x.latest_mean?.toFixed(3) ?? '—' },
                        { key: 'latest_std', label: 'SD', render: (x) => x.latest_std?.toFixed(3) ?? '—' },
                        { key: 'latest_min', label: 'Min–max', render: (x) => (x.latest_min != null ? `${x.latest_min.toFixed(3)} – ${x.latest_max.toFixed(3)}` : '—') },
                        { key: 'latest_coverage', label: 'Valid coverage', render: (x) => (x.latest_coverage != null ? `${(x.latest_coverage * 100).toFixed(1)}%` : '—') },
                        { key: 'change_first_to_last', label: 'Δ mean (first→latest)', render: (x) => (x.change_first_to_last != null ? x.change_first_to_last.toFixed(3) : '—') },
                      ]} />
                      <div className="h-56" role="img" aria-label="Latest mean index per region">
                        <ResponsiveContainer>
                          <BarChart data={chart}>
                            <CartesianGrid stroke="#1e2d44" strokeDasharray="3 3" />
                            <XAxis dataKey="name" stroke="#94a3b8" fontSize={11} />
                            <YAxis domain={[-1, 1]} stroke="#94a3b8" fontSize={11} />
                            <Tooltip contentStyle={{ background: '#0f1b2d', border: '1px solid #1e2d44' }} />
                            <Bar dataKey="mean" name="Latest mean" fill="#22d3ee" />
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                      <Notice>An index difference between dates is not proof of deforestation or urbanisation; season, clouds and sensor effects also change it.</Notice>
                    </div>
                  )
                }}
              </Async>
            </Card>
          </div>
        )}
      </Async>
    </>
  )
}