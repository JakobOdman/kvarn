import { CircleAlert, CircleCheck, CircleHelp, ChevronDown } from 'lucide-react'
import { useState } from 'react'
import type { Check } from '../api'

const ICONS = { ok: <CircleCheck />, fail: <CircleAlert />, unknown: <CircleHelp /> }

/** "4 av 5 kontroller OK", which opens to every check per document with what it found. */
export function Checks({ checks }: { checks: Check[] }) {
  const [open, setOpen] = useState(false)
  if (!checks.length) return null

  const ok = checks.filter((c) => c.status === 'ok').length
  const failed = checks.filter((c) => c.status === 'fail').length
  const unknown = checks.length - ok - failed
  const status = failed ? 'fail' : unknown ? 'unknown' : 'ok'

  return (
    <div className={`checks ${status} ${open ? 'open' : ''}`}>
      <button className="checks-head" onClick={() => setOpen(!open)}>
        <span className="checks-icon">{ICONS[status]}</span>
        <span>
          {ok} av {checks.length} kontroller OK
          {failed > 0 && <span className="checks-extra"> · {failed} stämmer inte</span>}
          {unknown > 0 && <span className="checks-extra"> · {unknown} kan inte kontrolleras</span>}
        </span>
        <ChevronDown className="checks-chevron" />
      </button>
      <div className="collapse">
        <div className="collapse-inner">
          <ul className="checks-list">
            {checks.map((c, i) => (
              <li key={i} className={c.status}>
                <span className="checks-icon">{ICONS[c.status]}</span>
                <span className="checks-text">
                  <span>{c.description}</span>
                  <span className="checks-message">
                    {c.document} · {c.message}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}
