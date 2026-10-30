import { useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { useApi } from '../hooks/useApi.js'
import { jobsApi } from '../api/services.js'
import { Async, Badge, Card, EmptyState, ErrorState, Field, Loading, Notice, PageHeader, Table, fmtDate } from '../components/ui.jsx'

const TONE = { queued: 'neutral', running: 'info', completed: 'ok', succeeded: 'ok', failed: 'bad' }
const LABEL = { queued: 'Queued', running: 'Running', completed: 'Completed', succeeded: 'Completed', failed: 'Failed' }
const StatusBadge = ({ s }) => <Badge tone={TONE[s] || 'neutral'}>{LABEL[s] || s}</Badge>

function JobDetail({ id }) {
  const state = useApi(() => jobsApi.get(id), [id])
  if (state.loading) return <Loading />
  if (state.error) return <ErrorState message={state.error} onRetry={state.reload} />
  const j = state.data
  return (
    <dl className="space-y-2 text-sm">
      <div><dt className="label">ID</dt><dd className="font-mono text-xs">{j.id}</dd></div>
      <div><dt className="label">Kind</dt><dd>{j.kind}</dd></div>
      <div><dt className="label">Status</dt><dd><StatusBadge s={j.status} /></dd></div>
      <div><dt className="label">Created</dt><dd>{fmtDate(j.created_utc)}</dd></div>
      {j.region && <div><dt className="label">Region</dt><dd>{j.region}</dd></div>}
      {j.index_name && <div><dt className="label">Index</dt><dd>{j.index_name}</dd></div>}
      {j.started_utc && <div><dt className="label">Started / completed</dt><dd>{fmtDate(j.started_utc)} / {j.completed_utc ? fmtDate(j.completed_utc) : '—'}</dd></div>}
      {j.error_details && <Notice tone="warn">{j.error_details}</Notice>}
      {j.result?.data_kind === 'synthetic_test_fixture' && <Notice tone="warn">SYNTHETIC test fixture: not a satellite observation.</Notice>}
      {j.result && Object.keys(j.result).length > 0 && (
        <details open><summary className="label cursor-pointer">Result</summary>
          <pre className="mt-1 max-h-72 overflow-auto rounded bg-navy-900 p-2 text-[11px] text-slate-300">{JSON.stringify(j.result, null, 2)}</pre>
        </details>
      )}
    </dl>
  )
}

export default function Jobs() {
  const state = useApi(() => jobsApi.list())
  const [sel, setSel] = useState(null)

  return (
    <>
      <PageHeader title="Analysis Jobs" description="Queued, running, completed and failed analysis jobs."
        action={<button className="btn" onClick={state.reload}><RefreshCw size={14} aria-hidden="true" /> Refresh</button>} />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card title="Jobs" className="xl:col-span-2">
          <Async state={state}>
            {(d) => d.items.length === 0 ? (
              <EmptyState title="No jobs yet" text="Jobs appear here after you submit a processing job through the API (POST /api/jobs) or the processing CLI. See docs/SATELLITE_PROCESSING.md." />
            ) : (
              <Table rows={d.items} rowKey={(r) => r.id} selectedKey={sel} onRowClick={(r) => setSel(r.id)} columns={[
                { key: 'id', label: 'ID' }, { key: 'kind', label: 'Kind' },
                { key: 'status', label: 'Status', render: (r) => <StatusBadge s={r.status} /> },
                { key: 'created_utc', label: 'Created', render: (r) => fmtDate(r.created_utc) },
              ]} />
            )}
          </Async>
        </Card>
        <div className="space-y-4">
          <Card title="Job details">
            {sel ? <JobDetail id={sel} /> : <p className="text-xs text-slate-400">Select a job to see its details.</p>}
          </Card>
          <Card title="Submitting jobs">
            <Notice>Jobs are submitted with <span className="font-mono">POST /api/jobs</span> (scene_processing or change_detection) or the processing CLI, because they need a local scene folder. This page shows their status and results.</Notice>
          </Card>
        </div>
      </div>
    </>
  )
}
