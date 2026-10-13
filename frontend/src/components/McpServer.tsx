import { updateFolder, type Folder } from '../api'
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
        </>
      )}
    </div>
  )
}
