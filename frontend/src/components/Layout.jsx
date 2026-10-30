import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, Link } from 'react-router-dom'
import {
  Activity, BookOpen, Database, Gauge, LayoutDashboard, ListChecks, Map as MapIcon,
  MapPinned, Menu, PanelLeftClose, PanelLeftOpen, X,
} from 'lucide-react'
import { useApi } from '../hooks/useApi.js'
import { healthApi } from '../api/services.js'

export const NAV = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/explorer', label: 'Geospatial Explorer', icon: MapIcon },
  { to: '/temporal', label: 'Temporal Change', icon: Activity },
  { to: '/datasets', label: 'Satellite Datasets', icon: Database },
  { to: '/regional', label: 'Regional Analytics', icon: MapPinned },
  { to: '/benchmarks', label: 'Big Data Benchmarks', icon: Gauge },
  { to: '/jobs', label: 'Analysis Jobs', icon: ListChecks },
  { to: '/about', label: 'About & Methodology', icon: BookOpen },
]

function Logo({ compact }) {
  return (
    <Link to="/" className="flex items-center gap-2" aria-label="GEONOVA home">
      <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden="true">
        <circle cx="16" cy="16" r="11" fill="none" stroke="#22d3ee" strokeWidth="2" />
        <path d="M5 16h22M16 5c5 4 5 18 0 22M16 5c-5 4-5 18 0 22" fill="none" stroke="#14b8a6" strokeWidth="1.5" />
      </svg>
      {!compact && <span className="text-base font-semibold tracking-[0.18em] text-white">GEONOVA</span>}
    </Link>
  )
}

function NavList({ collapsed, onNavigate }) {
  return (
    <nav aria-label="Main" className="flex-1 space-y-1 px-2 py-3">
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          title={collapsed ? label : undefined}
          className={({ isActive }) =>
            `flex items-center gap-3 rounded-md px-3 py-2 text-sm ${
              isActive ? 'bg-navy-700 text-accent' : 'text-slate-300 hover:bg-navy-700 hover:text-white'
            } ${collapsed ? 'justify-center' : ''}`
          }
        >
          <Icon size={18} aria-hidden="true" />
          {!collapsed && <span>{label}</span>}
        </NavLink>
      ))}
    </nav>
  )
}

function ApiStatus() {
  const { data, error, loading } = useApi(() => healthApi.get())
  const tone = loading ? 'bg-slate-500' : error ? 'bg-red-500' : 'bg-teal-400'
  const text = loading ? 'Checking API…' : error ? 'API unreachable' : `API ${data.status}`
  return (
    <span className="flex items-center gap-2 text-xs text-slate-300" role="status">
      <span className={`h-2 w-2 rounded-full ${tone}`} aria-hidden="true" />
      {text}
    </span>
  )
}

export default function Layout() {
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const { pathname } = useLocation()
  const current = NAV.find((n) => (n.end ? pathname === n.to : pathname.startsWith(n.to)))

  useEffect(() => { setMobileOpen(false) }, [pathname])

  return (
    <div className="flex h-full bg-navy-900">
      {/* Desktop sidebar */}
      <aside className={`hidden shrink-0 flex-col border-r border-navy-600 bg-navy-950 md:flex ${collapsed ? 'w-16' : 'w-60'}`}>
        <div className={`flex h-14 items-center border-b border-navy-600 ${collapsed ? 'justify-center' : 'px-4'}`}>
          <Logo compact={collapsed} />
        </div>
        <NavList collapsed={collapsed} />
        <button
          className="m-2 flex items-center justify-center gap-2 rounded-md px-3 py-2 text-xs text-slate-400 hover:bg-navy-700 hover:text-white"
          onClick={() => setCollapsed((c) => !c)}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <PanelLeftOpen size={16} /> : <><PanelLeftClose size={16} /> Collapse</>}
        </button>
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-[1100] md:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="absolute inset-0 bg-black/60" onClick={() => setMobileOpen(false)} />
          <aside className="relative flex h-full w-64 flex-col bg-navy-950">
            <div className="flex h-14 items-center justify-between border-b border-navy-600 px-4">
              <Logo />
              <button onClick={() => setMobileOpen(false)} aria-label="Close menu"><X size={18} /></button>
            </div>
            <NavList onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-navy-600 bg-navy-950 px-4">
          <div className="flex min-w-0 items-center gap-3">
            <button className="md:hidden" onClick={() => setMobileOpen(true)} aria-label="Open menu"><Menu size={20} /></button>
            <nav aria-label="Breadcrumb" className="min-w-0 truncate text-sm text-slate-400">
              <Link to="/" className="hover:text-white">GEONOVA</Link>
              {current && !current.end && <><span className="mx-2">/</span><span className="text-slate-100">{current.label}</span></>}
            </nav>
          </div>
          <div className="flex items-center gap-4">
            <span className="hidden text-xs text-slate-500 lg:inline">Sentinel-2 L2A · research prototype</span>
            <ApiStatus />
          </div>
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
