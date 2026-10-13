import { useEffect, useState } from 'react'
import { createMcpDescription, getMcpDescription, updateFolder, type Folder, type McpDescription } from '../api'
import { formatTime } from '../labels'
import { Copy } from './ApiKey'
import { Toggle } from './Toggle'

/** The folder's MCP server: Claude and Copilot Studio ask questions about the live extraction with the folder's key. */
export function McpServer({ folder, onFolderChanged }: { folder: Folder; onFolderChanged: (folder: Folder) => void }) {
  async function change(on: boolean) {
    onFolderChanged(await updateFolder(folder.id, { mcp_enabled: on }))
  }

  return (
    <div className="api-key">
      <Toggle
        label="MCP-server"
        description="Claude och Copilot Studio ställer frågor om samlingens aktuella tabell, med samlingens API-nyckel."
        checked={folder.mcp_enabled}
        onChange={change}
      />
      {folder.mcp_enabled && (
        <>
          <span className="caps">Adress</span>
          <Copy value={`${location.origin}/api/public/folders/${folder.id}/mcp`} />
          {!folder.api_key_created && <p className="queue-meta">Skapa en API-nyckel ovan för att ansluta.</p>}
          <p className="queue-meta">
            <strong>Claude:</strong> Inställningar → Connectors → Lägg till anpassad connector. Ange adressen och,
            under Request headers, <code>Authorization</code> med värdet <code>Bearer &lt;nyckel&gt;</code>.
          </p>
          <p className="queue-meta">
            <strong>Copilot Studio:</strong> Verktyg → Lägg till verktyg → Model Context Protocol. Ange adressen, välj
            API-nyckel som header med namnet <code>Authorization</code> och värdet <code>Bearer &lt;nyckel&gt;</code>.
          </p>
          <Description key={folder.id} folderId={folder.id} />
        </>
      )}
    </div>
  )
}

/** What Claude is told about the folder: written by the AI from the template and the tables, editable. */
function Description({ folderId }: { folderId: string }) {
  const [saved, setSaved] = useState<McpDescription | null>(null)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function show(d: McpDescription) {
    setSaved(d)
    setDraft(d.description ?? '')
  }

  useEffect(() => {
    getMcpDescription(folderId).then(show)
  }, [folderId])

  async function create() {
    setBusy(true)
    setError(null)
    try {
      show(await createMcpDescription(folderId))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function save() {
    await updateFolder(folderId, { mcp_description: draft })
    show(await getMcpDescription(folderId))
  }

  if (!saved) return null
  return (
    <>
      <span className="caps">Beskrivning</span>
      <p className="queue-meta">
        Det Claude får veta om samlingen när den ansluter: vad tabellerna innehåller och vad man ska tänka på.
      </p>
      {saved.stale && (
        <p className="queue-meta">Mallen eller dokumenten har ändrats sedan beskrivningen skapades.</p>
      )}
      {saved.description !== null && (
        <textarea rows={10} value={draft} onChange={(e) => setDraft(e.target.value)} />
      )}
      {error && <p className="queue-meta">{error}</p>}
      <div className="item-actions">
        {saved.created && <span className="queue-meta faint">Skapad {formatTime(saved.created)}</span>}
        <span className="spacer" />
        {saved.description !== null && (
          <button onClick={save} disabled={draft === saved.description}>
            Spara
          </button>
        )}
        <button onClick={create} disabled={busy}>
          {busy ? 'Skapar …' : saved.description === null ? 'Skapa MCP-beskrivning' : 'Skapa ny'}
        </button>
      </div>
    </>
  )
}
