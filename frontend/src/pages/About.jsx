import { Card, INDEX_INFO, PageHeader } from '../components/ui.jsx'

export default function About() {
  return (
    <>
      <PageHeader title="About & Methodology" description="What GEONOVA studies, how indices are computed, and what the results do and do not show." />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card title="Objectives">
          <ul className="list-disc space-y-1 pl-5 text-sm text-slate-300">
            <li>Measure multi-temporal change in vegetation, water and built-up indices for Ahmedabad, Surat, Pune and Bengaluru (2021–2026).</li>
            <li>Evaluate how robust those measurements are to clouds, missing scenes, season and resampling.</li>
            <li>Compare Pandas and PySpark (local mode) for runtime, scaling and numerical agreement.</li>
          </ul>
        </Card>
        <Card title="Sentinel-2 Level-2A">
          <p className="text-sm text-slate-300">Surface-reflectance products from the Copernicus Sentinel-2 mission (10, 20 and 60 m bands, about 5-day revisit with two satellites). Reflectance = (DN + offset) / 10000, where the offset (−1000 from processing baseline 04.00, 25 Jan 2022) is read from each product&apos;s metadata. DN = 0 is NoData. A scene classification layer (SCL) masks clouds and shadows.</p>
        </Card>
        <Card title="Spectral indices" className="xl:col-span-2">
          <div className="grid gap-3 md:grid-cols-3">
            {Object.entries(INDEX_INFO).map(([k, v]) => (
              <div key={k} className="rounded-md border border-navy-600 bg-navy-900 p-3">
                <div className="font-semibold" style={{ color: v.color }}>{v.label} <span className="text-xs font-normal text-slate-400">· {v.name}</span></div>
                <p className="mt-2 font-mono text-sm text-slate-200">{v.formula}</p>
                <p className="mt-1 text-xs text-slate-500">Bands {v.bands}. Range −1 to +1.</p>
              </div>
            ))}
          </div>
        </Card>
        <Card title="Temporal change detection">
          <p className="text-sm text-slate-300">For each region we average an index over valid (cloud-free) pixels at each date and compare dates: ΔI = I<sub>later</sub> − I<sub>earlier</sub>. Coverage (share of valid pixels) is reported alongside every value.</p>
        </Card>
        <Card title="Pandas vs PySpark evaluation">
          <p className="text-sm text-slate-300">Both engines run the same aggregation on the same Parquet data. We record mean and SD of runtime over repeated runs after warm-up, and check numerical agreement with a tolerance rule. PySpark runs in local mode on one machine, so results do not represent a distributed cluster.</p>
        </Card>
        <Card title="Limitations and data provenance" className="xl:col-span-2">
          <ul className="list-disc space-y-1 pl-5 text-sm text-slate-300">
            <li>This is a research prototype. A change in an index is evidence, not proof, of deforestation or urbanization.</li>
            <li>Region boxes are approximate and under review.</li>
            <li>Satellite data come from Sentinel-2 L2A (Copernicus). Nothing on this site is shown unless the backend returned it.</li>
            <li>Benchmarks on synthetic data measure speed only and are labelled as such.</li>
          </ul>
        </Card>
      </div>
    </>
  )
}