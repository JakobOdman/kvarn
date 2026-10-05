import { useEffect, useState } from 'react'
import type { Extraction } from '../api'

const clock = (seconds: number) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`

/** "Dokument 2 av 5 · namn" with a bar that fills per document and shimmers where it is working, plus time spent. */
export function Progress({ extraction }: { extraction: Extraction }) {
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  const docs = extraction.documents
  const finished = docs.filter((d) => d.status === 'done' || d.status === 'error').length
  const current = docs.find((d) => d.status === 'running')
  const elapsed = Math.max(0, Math.round((now - new Date(extraction.created).getTime()) / 1000))

  return (
    <div className="progress">
      <div className="progress-text">
        <span>{current ? `Dokument ${finished + 1} av ${docs.length} · ${current.name}` : 'Startar…'}</span>
        <span className="progress-time">{clock(elapsed)}</span>
      </div>
      <div className="progress-track">
        <div className="progress-done" style={{ width: `${(finished / docs.length) * 100}%` }} />
        {current && (
          <div
            className="progress-current"
            style={{ left: `${(finished / docs.length) * 100}%`, width: `${100 / docs.length}%` }}
          />
        )}
      </div>
    </div>
  )
}
