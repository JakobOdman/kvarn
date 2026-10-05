import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import type { ReactNode } from 'react'

/** The left column, which folds in to a thin rail so the main view gets the width. */
export function Side({
  collapsed,
  onToggle,
  title,
  children,
}: {
  collapsed: boolean
  onToggle: () => void
  title: string // what the rail opens, e.g. "Visa samling och mall"
  children: ReactNode
}) {
  return (
    <div className={`side ${collapsed ? 'collapsed' : ''}`}>
      <button className="side-toggle" title={collapsed ? title : 'Fäll in'} onClick={onToggle}>
        {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
      </button>
      <div className="side-inner">{children}</div>
    </div>
  )
}
