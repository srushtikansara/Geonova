import axios from 'axios'

// Centralised Axios client. The backend mounts all routes under /api.
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export const client = axios.create({
  baseURL: `${API_BASE_URL}/api`,
  timeout: 15000,
})

/** Turn any Axios error into a short message safe to show the user. */
export function errorMessage(err) {
  if (err?.response) {
    const d = err.response.data?.detail
    const detail = typeof d === 'string' ? d : Array.isArray(d) ? d.map((x) => x.msg).join('; ') : ''
    return `API error ${err.response.status}${detail ? `: ${detail}` : ''}`
  }
  if (err?.code === 'ECONNABORTED') return 'The API request timed out.'
  if (err?.request) return `Cannot reach the backend at ${API_BASE_URL}. Is it running?`
  return err?.message || 'Unexpected error.'
}
