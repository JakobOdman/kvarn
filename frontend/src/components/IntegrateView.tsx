import { Folder as FolderIcon } from 'lucide-react'
import { useEffect, useState } from 'react'
import { listFolders, listTemplates, type Folder, type Template } from '../api'
import { ApiKey } from './ApiKey'

const status = (f: Folder) =>
  !f.auto_extract ? 'Ingen aktuell tabell' : f.api_key_created ? 'API-nyckel finns' : 'Ingen API-nyckel'

/** Other systems (Qlik, Power BI, Excel) read a folder's live extraction with the folder's API key. */
export function IntegrateView() {
  const [folders, setFolders] = useState<Folder[]>([])
  const [templates, setTemplates] = useState<Template[]>([])
  const [folderId, setFolderId] = useState<string | null>(null)

  useEffect(() => {
    listFolders().then(setFolders)
    listTemplates().then(setTemplates)
  }, [])

  const folder = folders.find((f) => f.id === folderId)
  const changed = (f: Folder) => setFolders((all) => all.map((x) => (x.id === f.id ? f : x)))

  return (
    <>
      <section className="card">
        <span className="caps">Samlingar</span>
        <ul className="queue">
          {folders.map((f) => (
            <li
              key={f.id}
              className={`done ${f.id === folderId ? 'selected' : ''}`}
              onClick={() => setFolderId(f.id)}
            >
              <span className="icon">
                <FolderIcon />
              </span>
              <div>
                <div className="queue-name">{f.name}</div>
                <div className="queue-meta">{status(f)}</div>
              </div>
            </li>
          ))}
        </ul>
      </section>

      {!folder ? (
        <div className="empty">Välj en samling</div>
      ) : (
        <div className="card integrate">
          <h2>{folder.name}</h2>
          {folder.auto_extract ? (
            <ApiKey
              key={folder.id}
              folder={folder}
              template={templates.find((t) => t.id === folder.template_id)}
              onFolderChanged={changed}
            />
          ) : (
            <p className="queue-meta">
              Samlingen har ingen aktuell tabell att hämta. Välj en mall och slå på Extrahera automatiskt för
              samlingen under Läsa.
            </p>
          )}
        </div>
      )}
    </>
  )
}
