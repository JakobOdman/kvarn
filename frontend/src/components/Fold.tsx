import { ChevronRight } from 'lucide-react'
import { useState, type ReactNode } from 'react'

/** A heading with a summary that opens and closes what is under it. */
export function Fold({ title, summary, startOpen = false, children }: {
  title: string
  summary: ReactNode
  startOpen?: boolean
  children: ReactNode
}) {
  const [open, setOpen] = useState(startOpen)
  return (
    <div className={`fold ${open ? 'open' : ''}`}>
      <button className="fold-head" onClick={() => setOpen(!open)}>
        <ChevronRight />
        <span className="caps">{title}</span>
        <span className="fold-summary">{summary}</span>
      </button>
      <div className="collapse">
        <div className="collapse-inner">{children}</div>
      </div>
    </div>
  )
}
