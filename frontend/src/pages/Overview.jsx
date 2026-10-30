import { Link } from 'react-router-dom'
import { Activity, Database, Gauge, ListChecks, MapPinned, Map as MapIcon, BookOpen } from 'lucide-react'
import { useApi } from '../hooks/useApi.js'
import { analyticsApi, benchmarksApi, datasetsApi, jobsApi, regionsApi } from '../api/services.js'
import { Async, Badge, Card, EmptyState, INDEX_INFO, Notice, PageHeader, Stat, Table, fmtDate } from '../components/ui.jsx'

const val = (state, pick) => (state.loading ? '…' : state.error ? 'n/a' : pick(state.data))

export default function Overview() {
  const regions = useApi(() => regionsApi.list())
  const datasets = useApi(() => datasetsApi.list())
  const summary = useApi(() => analyticsApi.summary())
  const benchmarks = useApi(() => benchmarksApi.list())
  const jobs = useApi(() => jobsApi.list())

  const links = [
    { to: '/explorer', label: 'Geospatial Explorer', icon: MapIcon },
    { to: '/temporal', label: 'Temporal Change', icon: Activity },
    { to: '/datasets', label: 'Datasets', icon: Database },
    { to: '/regional', label: 'Regional Analytics', icon: MapPinned },
    { to: '/benchmarks', label: 'Benchmarks', icon: Gauge },
    { to: '/about', label: 'Methodology', icon: BookOpen },
  ]

  return (
    <>
      <PageHeader
        title="Overview"
        description="Environmental change detection from Sentinel-2 L2A over Ahmedabad, Surat, Pune and Bengaluru. Every number on this page comes from the backend API; nothing is estimated."
      />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Configured regions" icon={MapPinned} value={val(regions, (d) => d.count)} hint="Metadata only; not the same as analysed" />
        <Stat label="Satellite datasets" icon={Database} value={val(datasets, (d) => d.count)} hint="Registered scenes/products" />
        <Stat label="Completed analyses" icon={Activity} value={val(summary, (d) => (d.available ? d.regions_analysed : '0'))} hint={val(summary, (d) => d.reason || 'Regions with real results')} />
        <Stat label="Benchmark runs" icon={Gauge} value={val(benchmarks, (d) => d.count)} hint="Measured Pandas vs PySpark runs" />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card title="Environmental indicators" subtitle="Regional means appear here once analyses exist" className="xl:col-span-2">
          <Async state={summary}>
            {(d) =>
              d.available ? (
                <p className="text-sm text-slate-300">{d.regions_analysed} region(s) analysed from {d.scenes_processed} scene(s).</p>
              ) : (
                <div className="grid gap-3 sm:grid-cols-3">
                  {Object.entries(INDEX_INFO).map(([k, v]) => (
                    <div key={k} className="rounded-md border border-navy-600 bg-navy-900 p-3">
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-semibold" style={{ color: v.color }}>{v.label}</span>
                        <Badge>No data</Badge>
                      </div>
                      <p className="mt-1 text-xs text-slate-400">{v.name}</p>
                      <p className="mt-2 font-mono text-[11px] text-slate-500">{v.formula}</p>
                    </div>
                  ))}
                  <div className="sm:col-span-3"><Notice>{d.reason || 'No analysis has been run yet.'}</Notice></div>
                </div>
              )
            }
          </Async>
        </Card>

        <Card title="Regional activity" subtitle="Configured vs analysed">
          <Async state={regions}>
            {(d) =>
              d.items.length === 0 ? (
                <EmptyState title="No regions configured" />
              ) : (
                <ul className="divide-y divide-navy-600">
                  {d.items.map((r) => (
                    <li key={r.id} className="flex items-center justify-between py-2 text-sm">
                      <span>{r.name}</span>
                      <span className="flex gap-2">
                        <Badge tone="info">Configured</Badge>
                        <Badge tone={r.analysed ? 'ok' : 'neutral'}>{r.analysed ? 'Analysed' : 'Not analysed'}</Badge>
                      </span>
                    </li>
                  ))}
                </ul>
              )
            }
          </Async>
        </Card>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card title="Recent jobs" className="xl:col-span-2" action={<Link to="/jobs" className="text-xs text-accent hover:underline">All jobs</Link>}>
          <Async state={jobs}>
            {(d) =>
              d.items.length === 0 ? (
                <EmptyState icon={ListChecks} title="No jobs yet" text="Processing jobs will be listed here after one is submitted (see Analysis Jobs)." />
              ) : (
                <Table
                  rowKey={(r) => r.id}
                  rows={d.items.slice(0, 5)}
                  columns={[
                    { key: 'id', label: 'ID' },
                    { key: 'kind', label: 'Kind' },
                    { key: 'status', label: 'Status', render: (r) => <Badge>{r.status}</Badge> },
                    { key: 'created_utc', label: 'Created', render: (r) => fmtDate(r.created_utc) },
                  ]}
                />
              )
            }
          </Async>
        </Card>
        <Card title="Quick navigation">
          <ul className="grid grid-cols-2 gap-2">
            {links.map(({ to, label, icon: Icon }) => (
              <li key={to}>
                <Link to={to} className="flex items-center gap-2 rounded-md border border-navy-600 bg-navy-900 px-3 py-2 text-xs text-slate-200 hover:border-accent hover:text-accent">
                  <Icon size={14} aria-hidden="true" /> {label}
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  )
}