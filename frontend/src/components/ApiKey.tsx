import { ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { createApiKey, deleteApiKey, type Folder, type Template } from '../api'
import { formatTime } from '../labels'

/** The folder's API key, for reading its live extraction from other systems (Qlik, Power BI, Excel).
 *  The key is shown once, right after it is made. */
export function ApiKey({
  folder,
  template,
  onFolderChanged,
}: {
  folder: Folder
  template: Template | undefined
  onFolderChanged: (folder: Folder) => void
}) {
  const [key, setKey] = useState<string | null>(null)
  const [open, setOpen] = useState<Set<string>>(new Set()) // tables showing their address

  function toggle(table: string) {
    const next = new Set(open)
    if (!next.delete(table)) next.add(table)
    setOpen(next)
  }

  async function create() {
    if (folder.api_key_created && !confirm('Skapa en ny nyckel? Den gamla slutar fungera direkt.')) return
    setKey((await createApiKey(folder.id)).key)
    onFolderChanged({ ...folder, api_key_created: new Date().toISOString() })
  }

  async function remove() {
    if (!confirm('Ta bort nyckeln? System som använder den slutar få data.')) return
    await deleteApiKey(folder.id)
    setKey(null)
    onFolderChanged({ ...folder, api_key_created: null })
  }

  const base = `${location.origin}/api/public/folders/${folder.id}/tables`
  return (
    <div className="api-key">
      <p className="queue-meta">
        Andra system hämtar samlingens aktuella tabell som JSON. Nyckeln skickas i headern{' '}
        <code>Authorization: Bearer &lt;nyckel&gt;</code>.
      </p>
      {key && (
        <>
          <span className="caps">Nyckel</span>
          <p className="queue-meta">Kopiera nyckeln nu. Den visas bara den här gången.</p>
          <Copy value={key} />
        </>
      )}
      <span className="caps">Tabeller</span>
      <ul className="api-tables">
        {(template?.tables ?? []).map((t) => (
          <li key={t.name} className={open.has(t.name) ? 'open' : ''}>
            <button className="api-table" onClick={() => toggle(t.name)}>
              <ChevronRight />
              <span>{t.name}</span>
              <span className="queue-meta faint">{t.fields.length} fält</span>
            </button>
            {open.has(t.name) && <Copy value={`${base}/${encodeURIComponent(t.name)}`} />}
          </li>
        ))}
      </ul>
      <div className="item-actions">
        {folder.api_key_created && (
          <span className="queue-meta faint">Nyckel skapad {formatTime(folder.api_key_created)}</span>
        )}
        <span className="spacer" />
        {folder.api_key_created && <button onClick={remove}>Ta bort</button>}
        <button onClick={create}>{folder.api_key_created ? 'Skapa ny nyckel' : 'Skapa API-nyckel'}</button>
      </div>
    </div>
  )
}

function Copy({ value }: { value: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="copy">
      <input readOnly value={value} onFocus={(e) => e.target.select()} />
      <button
        onClick={async () => {
          await navigator.clipboard.writeText(value)
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        }}
      >
        {copied ? 'Kopierad' : 'Kopiera'}
      </button>
    </div>
  )
}
