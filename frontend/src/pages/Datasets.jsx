import { useMemo, useState } from 'react'
import { Search } from 'lucide-react'
import { useApi } from '../hooks/useApi.js'
import { datasetsApi } from '../api/services.js'
import { Async, Badge, Card, EmptyState, Field, PageHeader, Table } from '../components/ui.jsx'

export default function Datasets() {
  const state = useApi(() => datasetsApi.list())
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [selected, setSelected] = useState(null)

  const items = state.data?.items ?? []
  const statuses = useMemo(() => [...new Set(items.map((d) => d.status || d.processing_status).filter(Boolean))], [items])
  const rows = useMemo(
    () => items.filter((d) => (!status || (d.status || d.processing_status) === status) && (!q || JSON.stringify(d).toLowerCase().includes(q.toLowerCase()))),
    [items, q, status],
  )

  return (
    <>
      <PageHeader title="Satellite Datasets" description="Registered Sentinel-2 products and their processing status." />
      <Async state={state}>
        {(d) => items.length === 0 ? (
          <Card><EmptyState title="No datasets registered" text={d.note || 'Datasets will appear here once scenes are ingested.'} /></Card>
        ) : (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-2" title={`${rows.length} of ${items.length} datasets`}>
              <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Field label="Search" htmlFor="ds-q">
                  <div className="relative"><Search size={14} className="absolute left-3 top-3 text-slate-500" aria-hidden="true" />
                    <input id="ds-q" className="input pl-8" placeholder="Region, mission, date…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
                </Field>
                <Field label="Processing status" htmlFor="ds-s">
                  <select id="ds-s" className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
                    <option value="">All</option>
                    {statuses.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </Field>
              </div>
              {rows.length === 0 ? <EmptyState title="No datasets match the filters" /> : (
                <Table
                  rows={rows}
                  rowKey={(r, i) => r.id ?? i}
                  selectedKey={selected ? (selected.id ?? rows.indexOf(selected)) : undefined}
                  onRowClick={setSelected}
                  columns={[
                    { key: 'mission', label: 'Mission' },
                    { key: 'sensor', label: 'Sensor' },
                    { key: 'acquisition_date', label: 'Acquired' },
                    { key: 'region', label: 'Region' },
                    { key: 'status', label: 'Status', render: (r) => { const s = r.status || r.processing_status; return s ? <Badge>{s}</Badge> : '—' } },
                  ]}
                />
              )}
            </Card>
            <Card title="Dataset details">
              {!selected ? <p className="text-xs text-slate-400">Select a row to see its fields.</p> : (
                <dl className="space-y-2 text-sm">
                  {Object.entries(selected).map(([k, v]) => (
                    <div key={k}><dt className="label">{k}</dt><dd className="break-all text-slate-200">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</dd></div>
                  ))}
                </dl>
              )}
            </Card>
          </div>
        )}
      </Async>
    </>
  )
}
