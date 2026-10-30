import { AlertTriangle, Inbox, Loader2, RefreshCw } from 'lucide-react'

export function Card({ title, subtitle, action, children, className = '' }) {
  return (
    <section className={`card ${className}`}>
      {(title || action) && (
        <header className="flex items-start justify-between gap-3 border-b border-navy-600 px-4 py-3">
          <div>
            {title && <h2 className="text-sm font-semibold text-slate-100">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-slate-400">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      <div className="card-pad">{children}</div>
    </section>
  )
}

export function PageHeader({ title, description, action }) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-white">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-slate-400">{description}</p>}
      </div>
      {action}
    </div>
  )
}

const BADGES = {
  neutral: 'border-navy-600 bg-navy-700 text-slate-300',
  ok: 'border-teal-700 bg-teal-900/40 text-teal-300',
  warn: 'border-amber-700 bg-amber-900/30 text-amber-300',
  bad: 'border-red-700 bg-red-900/30 text-red-300',
  info: 'border-cyan-700 bg-cyan-900/30 text-cyan-300',
}
export function Badge({ tone = 'neutral', children }) {
  return <span className={`inline-flex items-center rounded border px-2 py-0.5 text-xs font-medium ${BADGES[tone]}`}>{children}</span>
}

export function Stat({ label, value, hint, icon: Icon }) {
  return (
    <div className="card card-pad">
      <div className="flex items-center justify-between">
        <span className="label">{label}</span>
        {Icon && <Icon size={16} className="text-accent" aria-hidden="true" />}
      </div>
      <div className="mt-2 text-2xl font-semibold tabular-nums text-white">{value}</div>
      {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
    </div>
  )
}

export function Loading({ text = 'Loading…' }) {
  return (
    <div role="status" className="flex items-center justify-center gap-2 py-10 text-sm text-slate-400">
      <Loader2 className="animate-spin" size={16} aria-hidden="true" /> {text}
    </div>
  )
}

export function ErrorState({ message, onRetry }) {
  return (
    <div role="alert" className="flex flex-col items-center gap-3 py-8 text-center">
      <AlertTriangle className="text-amber-400" size={24} aria-hidden="true" />
      <p className="max-w-md text-sm text-slate-300">{message}</p>
      {onRetry && (
        <button className="btn" onClick={onRetry}>
          <RefreshCw size={14} aria-hidden="true" /> Retry
        </button>
      )}
    </div>
  )
}

export function EmptyState({ title, text, icon: Icon = Inbox }) {
  return (
    <div className="flex flex-col items-center gap-2 py-8 text-center">
      <Icon className="text-slate-500" size={24} aria-hidden="true" />
      <p className="text-sm font-medium text-slate-200">{title}</p>
      {text && <p className="max-w-md text-xs text-slate-400">{text}</p>}
    </div>
  )
}

/** Renders loading / error / children for a useApi result. */
export function Async({ state, children }) {
  if (state.loading) return <Loading />
  if (state.error) return <ErrorState message={state.error} onRetry={state.reload} />
  return children(state.data)
}

export function Notice({ tone = 'info', children }) {
  const cls = tone === 'warn' ? 'border-amber-700/60 bg-amber-900/20 text-amber-200' : 'border-cyan-700/60 bg-cyan-900/20 text-cyan-100'
  return <div className={`rounded-md border px-3 py-2 text-xs ${cls}`}>{children}</div>
}

export function Table({ columns, rows, rowKey, onRowClick, selectedKey }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-navy-600">
        <thead>
          <tr>{columns.map((c) => <th key={c.key} scope="col" className="th">{c.label}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-navy-600">
          {rows.map((r, i) => {
            const k = rowKey ? rowKey(r, i) : i
            return (
              <tr
                key={k}
                onClick={onRowClick ? () => onRowClick(r) : undefined}
                className={`${onRowClick ? 'cursor-pointer hover:bg-navy-700' : ''} ${selectedKey === k ? 'bg-navy-700' : ''}`}
              >
                {columns.map((c) => <td key={c.key} className="td">{c.render ? c.render(r) : (r[c.key] ?? '—')}</td>)}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function Field({ label, htmlFor, children }) {
  return (
    <div>
      <label htmlFor={htmlFor} className="label mb-1 block">{label}</label>
      {children}
    </div>
  )
}

export function fmtDate(v) {
  if (!v) return '—'
  const d = new Date(v)
  return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleString()
}

export const INDEX_INFO = {
  ndvi: { label: 'NDVI', name: 'Vegetation', formula: '(NIR − Red) / (NIR + Red)', bands: 'B8, B4', color: '#34d399' },
  ndwi: { label: 'NDWI', name: 'Water (McFeeters)', formula: '(Green − NIR) / (Green + NIR)', bands: 'B3, B8', color: '#22d3ee' },
  ndbi: { label: 'NDBI', name: 'Built-up', formula: '(SWIR − NIR) / (SWIR + NIR)', bands: 'B11, B8', color: '#fb923c' },
}
