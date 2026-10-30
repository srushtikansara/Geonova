import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout.jsx'
import Overview from './pages/Overview.jsx'
import Explorer from './pages/Explorer.jsx'
import Temporal from './pages/Temporal.jsx'
import Datasets from './pages/Datasets.jsx'
import Regional from './pages/Regional.jsx'
import Benchmarks from './pages/Benchmarks.jsx'
import Jobs from './pages/Jobs.jsx'
import About from './pages/About.jsx'
import { EmptyState } from './components/ui.jsx'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Overview />} />
        <Route path="explorer" element={<Explorer />} />
        <Route path="temporal" element={<Temporal />} />
        <Route path="datasets" element={<Datasets />} />
        <Route path="regional" element={<Regional />} />
        <Route path="benchmarks" element={<Benchmarks />} />
        <Route path="jobs" element={<Jobs />} />
        <Route path="about" element={<About />} />
        <Route path="*" element={<EmptyState title="Page not found" text="Use the sidebar to navigate." />} />
      </Route>
    </Routes>
  )
}
