import { useEffect, useMemo, useState } from 'react'
import { ImageOverlay, MapContainer, Rectangle, TileLayer, Tooltip, useMap } from 'react-leaflet'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip as ChartTip, XAxis, YAxis } from 'recharts'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useApi } from '../hooks/useApi.js'
import { rastersApi, regionsApi } from '../api/services.js'
import { errorMessage } from '../api/client.js'
import { Async, Badge, Card, EmptyState, Field, INDEX_INFO, Notice, PageHeader } from '../components/ui.jsx'

const toBounds = (bbox) => [[bbox[1], bbox[0]], [bbox[3], bbox[2]]]
const CLASS_COLOURS = { water: '#2b7bba', vegetation: '#2e7d32', built: '#d73027', other: '#e0d3b8' }
const CLASS_LABELS = { water: 'Water', vegetation: 'Vegetation', built: 'Built-up / bare', other: 'Other' }
const LAYERS = [
  { key: 'ndvi', label: 'NDVI · vegetation' }, { key: 'ndwi', label: 'NDWI · water' }, { key: 'ndbi', label: 'NDBI · built-up' },
  { key: 'classes', label: 'Land-cover classes (indicative)' }, { key: 'change', label: 'Change between two dates' },
]

function FitTo({ bounds }) {
  const map = useMap()
  useEffect(() => { if (bounds) map.fitBounds(bounds, { padding: [30, 30] }) }, [bounds, map])
  return null
}

function GradientLegend({ legend }) {
  const stops = legend.stops
  const lo = stops[0].value, hi = stops[stops.length - 1].value
  const css = stops.map((s) => `${s.colour} ${(((s.value - lo) / (hi - lo)) * 100).toFixed(1)}%`).join(', ')
  return (
    <div>
      <p className="text-xs font-medium text-slate-200">{legend.label}</p>
      <div className="mt-2 h-3 rounded" style={{ background: `linear-gradient(to right, ${css})` }} role="img" aria-label={`Colour scale ${lo} to ${hi}`} />
      <div className="mt-1 flex justify-between text-[11px] text-slate-400"><span>{lo}</span><span>{((lo + hi) / 2).toFixed(1)}</span><span>{hi}</span></div>
      <p className="mt-1 text-[11px] text-slate-500">{legend.caption}</p>
    </div>
  )
}

function ClassLegend({ summary }) {
  return (
    <div>
      <p className="text-xs font-medium text-slate-200">Land-cover classes (indicative)</p>
      <ul className="mt-2 space-y-1">
        {(summary?.classes ?? Object.keys(CLASS_LABELS).map((k) => ({ key: k, label: CLASS_LABELS[k], colour: CLASS_COLOURS[k] }))).map((c) => (
          <li key={c.key} className="flex items-center gap-2 text-xs text-slate-300">
            <span className="inline-block h-3 w-3 rounded-sm border border-navy-600" style={{ background: c.colour }} />
            {c.label}{typeof c.fraction === 'number' ? ` · ${(c.fraction * 100).toFixed(1)}% of valid pixels` : ''}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[11px] text-slate-500">{summary?.note ?? 'Simple index-threshold rules; a convention, not a validated land-cover map.'}</p>
    </div>
  )
}

function LandCoverOverTime({ datasets }) {
  const [rows, setRows] = useState({ loading: true, error: null, data: [] })
  const key = datasets.map((d) => d.id).join(',')
  useEffect(() => {
    let alive = true
    setRows({ loading: true, error: null, data: [] })
    Promise.all(datasets.map((d) => rastersApi.classes(d.id).then((s) => ({ date: d.date, ...Object.fromEntries(s.classes.map((c) => [c.key, c.fraction == null ? null : +(c.fraction * 100).toFixed(2)])) }))))
      .then((data) => alive && setRows({ loading: false, error: null, data }))
      .catch((e) => alive && setRows({ loading: false, error: errorMessage(e), data: [] }))
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  if (rows.loading) return <p className="text-xs text-slate-400">Loading…</p>
  if (rows.error) return <Notice tone="warn">{rows.error}</Notice>
  return (
    <div className="space-y-2">
      <div className="h-64" role="img" aria-label="Land-cover mix by date">
        <ResponsiveContainer>
          <BarChart data={rows.data}>
            <CartesianGrid stroke="#1e2d44" strokeDasharray="3 3" />
            <XAxis dataKey="date" stroke="#94a3b8" fontSize={11} />
            <YAxis stroke="#94a3b8" fontSize={11} unit="%" domain={[0, 100]} />
            <ChartTip contentStyle={{ background: '#0f1b2d', border: '1px solid #1e2d44' }} formatter={(v) => `${v}%`} />
            <Legend />
            {Object.keys(CLASS_LABELS).map((k) => <Bar key={k} dataKey={k} name={CLASS_LABELS[k]} stackId="a" fill={CLASS_COLOURS[k]} />)}
          </BarChart>
        </ResponsiveContainer>
      </div>
      {rows.data.length < 2 && <Notice>Only one date is available. Process scenes from other years (same season) to see increases and decreases over time.</Notice>}
      <p className="text-[11px] text-slate-500">Share of valid (cloud-free) pixels per class on each date. Differences between dates can also come from season, clouds and the fixed thresholds; they are not proof of land-cover change.</p>
    </div>
  )
}

export default function Explorer() {
  const regionsState = useApi(() => regionsApi.list())
  const [sel, setSel] = useState('')
  const [layer, setLayer] = useState('ndvi')
  const [synthetic, setSynthetic] = useState(false)
  const [pick, setPick] = useState('')
  const [opacity, setOpacity] = useState(0.8)
  const layersState = useApi(() => rastersApi.layers({ ...(synthetic ? { include_synthetic: true } : {}) }), [synthetic])
  const [summary, setSummary] = useState(null)

  const regions = regionsState.data?.items ?? []
  const selected = useMemo(() => regions.find((r) => r.id === sel) || null, [regions, sel])
  const all = layersState.data?.items ?? []
  const inRegion = all.filter((l) => !sel || l.region === sel)

  // options for the chosen layer type: [{value, label, layerId?, datasetId, bounds, legend, data_kind}]
  const options = useMemo(() => {
    if (layer === 'change') {
      return inRegion.filter((l) => l.kind === 'change').map((l) => ({ value: l.id, label: `${l.earlier_date} → ${l.later_date} (${l.index.toUpperCase()})`, layer: l }))
    }
    const idx = layer === 'classes' ? 'ndvi' : layer
    return inRegion.filter((l) => l.kind === 'index' && l.index === idx).sort((a, b) => a.date.localeCompare(b.date))
      .map((l) => ({ value: l.id, label: l.date, layer: l }))
  }, [inRegion, layer])
  const current = options.find((o) => o.value === pick) || options[options.length - 1] || null
  const L = current?.layer
  const bounds = L?.bounds ?? (selected ? toBounds(selected.bbox) : null)
  const overlayUrl = !L ? null : layer === 'classes' ? rastersApi.classesUrl(L.dataset_id) : rastersApi.layerUrl(L.id)
  const idxStep = (d) => { const i = options.findIndex((o) => o === current); const n = options[i + d]; if (n) setPick(n.value) }
  const datasets = useMemo(() => {
    const seen = new Map()
    inRegion.filter((l) => l.kind === 'index' && l.index === 'ndvi').forEach((l) => seen.set(l.dataset_id, { id: l.dataset_id, date: l.date }))
    return [...seen.values()].sort((a, b) => a.date.localeCompare(b.date))
  }, [inRegion])

  useEffect(() => {
    setSummary(null)
    if (layer !== 'classes' || !L) return
    let alive = true
    rastersApi.classes(L.dataset_id).then((s) => alive && setSummary(s)).catch(() => {})
    return () => { alive = false }
  }, [layer, L?.dataset_id]) // eslint-disable-line react-hooks/exhaustive-deps

  const info = INDEX_INFO[layer]
  const isSynthetic = L?.data_kind === 'synthetic_test_fixture'

  return (
    <>
      <PageHeader title="Geospatial Explorer" description="Colour-coded satellite-derived layers on a base map: vegetation, water, built-up surfaces and change between dates. Layers appear only when processed rasters exist." />
      <Async state={regionsState}>
        {() => regions.length === 0 ? <EmptyState title="No regions configured" /> : (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_20rem]">
            <div className="space-y-4">
              <Card className="!p-0 overflow-hidden">
                <div className="h-[28rem] md:h-[36rem]">
                  <MapContainer center={[21.5, 73]} zoom={6} scrollWheelZoom className="h-full w-full">
                    <TileLayer url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
                      attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' />
                    {overlayUrl && L && <ImageOverlay key={overlayUrl} url={overlayUrl} bounds={L.bounds} opacity={opacity} />}
                    {regions.map((r) => (
                      <Rectangle key={r.id} bounds={toBounds(r.bbox)} interactive
                        pathOptions={{ color: r.id === sel ? '#22d3ee' : '#14b8a6', weight: r.id === sel ? 3 : 1.5, fill: false }}
                        eventHandlers={{ click: () => { setSel(r.id); setPick('') } }}>
                        <Tooltip sticky>{r.name} (configured region box)</Tooltip>
                      </Rectangle>
                    ))}
                    <FitTo bounds={bounds} />
                  </MapContainer>
                </div>
                <div className="space-y-2 border-t border-navy-600 p-3">
                  {isSynthetic && <Notice tone="warn">This layer is a SYNTHETIC test fixture (generated raster). It is not a satellite observation.</Notice>}
                  {layersState.error && <Notice tone="warn">{layersState.error}</Notice>}
                  {!layersState.loading && !layersState.error && !L && (
                    <Notice>{layer === 'change' ? 'No change comparison exists for this selection. Run a change_detection job on two processed dates.'
                      : 'No processed raster for this selection yet. Process a Sentinel-2 scene (see Analysis Jobs) and it will be drawn here.'}</Notice>
                  )}
                  {L && <p className="text-[11px] text-slate-500">Layer drawn from a processed GeoTIFF, reprojected to lon/lat for display. Colours are a display choice; the GeoTIFF holds the numbers.</p>}
                </div>
              </Card>

              <Card title="Land-cover mix by date" subtitle={selected ? selected.name : 'Select a region'}>
                {!sel ? <p className="text-xs text-slate-400">Select a region to compare dates.</p>
                  : datasets.length === 0 ? <EmptyState title="No processed dates" text="Process scenes for this region to see how the vegetation, water and built-up shares change over the years." />
                    : <LandCoverOverTime datasets={datasets} />}
              </Card>
            </div>

            <div className="space-y-4">
              <Card title="Layer">
                <div className="space-y-3">
                  <Field label="Region" htmlFor="region">
                    <select id="region" className="input" value={sel} onChange={(e) => { setSel(e.target.value); setPick('') }}>
                      <option value="">All regions</option>
                      {regions.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                    </select>
                  </Field>
                  <Field label="Layer" htmlFor="layer">
                    <select id="layer" className="input" value={layer} onChange={(e) => { setLayer(e.target.value); setPick('') }}>
                      {LAYERS.map((l) => <option key={l.key} value={l.key}>{l.label}</option>)}
                    </select>
                  </Field>
                  <Field label={layer === 'change' ? 'Comparison' : 'Date'} htmlFor="date">
                    <div className="flex gap-1">
                      <button type="button" className="btn !px-2" onClick={() => idxStep(-1)} aria-label="Earlier date" disabled={!current || options[0] === current}><ChevronLeft size={14} /></button>
                      <select id="date" className="input" value={current?.value ?? ''} onChange={(e) => setPick(e.target.value)} disabled={options.length === 0}>
                        {options.length === 0 ? <option value="">No data</option> : options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                      </select>
                      <button type="button" className="btn !px-2" onClick={() => idxStep(1)} aria-label="Later date" disabled={!current || options[options.length - 1] === current}><ChevronRight size={14} /></button>
                    </div>
                  </Field>
                  <Field label={`Opacity ${Math.round(opacity * 100)}%`} htmlFor="op">
                    <input id="op" type="range" min="0.2" max="1" step="0.05" value={opacity} onChange={(e) => setOpacity(Number(e.target.value))} className="w-full" />
                  </Field>
                  <label className="flex items-start gap-2 text-xs text-slate-300">
                    <input type="checkbox" className="mt-0.5" checked={synthetic} onChange={(e) => { setSynthetic(e.target.checked); setPick('') }} />
                    Include synthetic test fixtures (generated rasters; never real satellite observations)
                  </label>
                </div>
              </Card>

              <Card title="Legend">
                {layer === 'classes' ? <ClassLegend summary={summary} />
                  : L ? <GradientLegend legend={L.legend} />
                    : <p className="text-xs text-slate-400">The colour scale appears when a layer is shown.</p>}
                {info && <p className="mt-3 font-mono text-[11px] text-slate-400">{info.formula} · bands {info.bands}</p>}
              </Card>

              <Card title="Selected region">
                {!selected ? <p className="text-xs text-slate-400">Click a region box on the map or choose one above.</p> : (
                  <dl className="space-y-2 text-sm">
                    <div className="flex items-center justify-between"><dt className="font-semibold text-white">{selected.name}</dt>
                      <dd className="flex gap-1"><Badge tone={selected.analysed ? 'ok' : 'neutral'}>{selected.analysed ? 'Analysed' : 'Not analysed'}</Badge></dd></div>
                    <div><dt className="label">Location</dt><dd>{selected.state}, {selected.country}</dd></div>
                    <div><dt className="label">Bounding box (lon/lat)</dt><dd className="font-mono text-xs">{selected.bbox.join(', ')}</dd></div>
                  </dl>
                )}
              </Card>
            </div>
          </div>
        )}
      </Async>
    </>
  )
}
