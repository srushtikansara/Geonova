import { useCallback, useEffect, useRef, useState } from 'react'
import { errorMessage } from '../api/client.js'

/** Fetch helper returning {data, loading, error, reload}. Never fabricates data on failure. */
export function useApi(fn, deps = []) {
  const [state, setState] = useState({ data: null, loading: true, error: null })
  const alive = useRef(true)
  const run = useCallback(() => {
    setState((s) => ({ ...s, loading: true, error: null }))
    fn()
      .then((data) => alive.current && setState({ data, loading: false, error: null }))
      .catch((e) => alive.current && setState({ data: null, loading: false, error: errorMessage(e) }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  useEffect(() => {
    alive.current = true
    run()
    return () => { alive.current = false }
  }, [run])
  return { ...state, reload: run }
}
