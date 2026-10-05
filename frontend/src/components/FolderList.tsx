import { Folder as FolderIcon } from 'lucide-react'
import { useEffect, useState } from 'react'
import { createFolder, listFolders, type Folder } from '../api'

/** The folders, and a field for a new one. A folder is the documents that belong together, e.g. one tender. */
export function FolderList({ onOpen }: { onOpen: (folder: Folder) => void }) {
  const [folders, setFolders] = useState<Folder[]>([])
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listFolders().then(setFolders)
  }, [])

  async function create(e: React.FormEvent) {
    e.preventDefault()
    try {
      onOpen(await createFolder(name))
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <section className="card">
      <span className="caps">Samlingar</span>
      <ul className="queue">
        {folders.map((f) => (
          <li key={f.id} className="done" onClick={() => onOpen(f)}>
            <span className="icon">
              <FolderIcon />
            </span>
            <div>
              <div className="queue-name">{f.name}</div>
              <div className="queue-meta">{f.document_count} dokument</div>
            </div>
          </li>
        ))}
      </ul>
      <form className="new-folder" onSubmit={create}>
        <input placeholder="Ny samling" value={name} onChange={(e) => setName(e.target.value)} />
        <button className="primary" disabled={!name.trim()}>
          Skapa
        </button>
      </form>
      {error && <p className="read-warning">{error}</p>}
    </section>
  )
}
