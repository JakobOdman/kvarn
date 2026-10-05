export type Tab = 'read' | 'templates' | 'extract'
export const TABS: Record<Tab, string> = { templates: 'Mallar', read: 'Läsa', extract: 'Extrahera' }

/** Plain navbar links. The animated mega menu (commit fba4191) can come back when there are subcategories. */
export function NavMenu({ tab, onNavigate }: { tab: Tab; onNavigate: (tab: Tab) => void }) {
  return (
    <nav className="nav">
      {(Object.keys(TABS) as Tab[]).map((t) => (
        <button key={t} className={t === tab ? 'active' : ''} onClick={() => onNavigate(t)}>
          {TABS[t]}
        </button>
      ))}
    </nav>
  )
}
