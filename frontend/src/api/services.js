import { API_BASE_URL, client } from './client.js'

const get = (url, params) => client.get(url, { params }).then((r) => r.data)

export const healthApi = { get: () => get('/health') }
export const systemApi = { info: () => get('/system/info') }
export const regionsApi = { list: () => get('/regions'), get: (id) => get(`/regions/${id}`) }
export const datasetsApi = { list: () => get('/datasets') }
export const analyticsApi = {
  summary: (params) => get('/analytics/summary', params),
  regional: (params) => get('/analytics/regional', params),
  temporal: (params) => get('/analytics/temporal', params),
}
export const benchmarksApi = {
  list: () => get('/benchmarks'),
  get: (id) => get(`/benchmarks/${id}`),
  preflight: (rows) => get('/benchmarks/preflight', { rows }),
  start: (body) => client.post('/benchmarks', body).then((r) => r.data),
  cancel: (id) => client.post(`/benchmarks/${id}/cancel`).then((r) => r.data),
}
export const jobsApi = { list: () => get('/jobs'), get: (id) => get(`/jobs/${id}`) }
export const rastersApi = {
  layers: (params) => get('/rasters/layers', params),
  classes: (datasetId) => get(`/rasters/classes/${datasetId}`),
  layerUrl: (id) => `${API_BASE_URL}/api/rasters/${id}/preview.png`,
  classesUrl: (datasetId) => `${API_BASE_URL}/api/rasters/classes/${datasetId}/preview.png`,
}
