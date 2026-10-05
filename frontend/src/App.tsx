import { useEffect, useState } from 'react'
import { logout, me, type Folder, type User } from './api'
import { DocumentView } from './components/DocumentView'
import { ExtractView } from './components/ExtractView'
import { FileQueue } from './components/FileQueue'
import { FolderList } from './components/FolderList'
import { Login } from './components/Login'
import { NavMenu, type Tab } from './components/NavMenu'
import { Side } from './components/Side'
import { TemplateEditor } from './components/TemplateEditor'
import { Wordmark } from './components/Wordmark'

export default function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined) // undefined while checking
  const [tab, setTab] = useState<Tab>('templates')
  const [folder, setFolder] = useState<Folder | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState(false) // Läsa's left column folded in while a document is open
  const [version, setVersion] = useState(0) // bumped to reload the document list

  useEffect(() => {
    me().then(setUser)
  }, [])

  async function signOut() {
    await logout()
    setUser(null)
    setFolder(null)
    setSelected(null)
    setTab('templates')
  }

  function openDocument(jobId: string | null) {
    setSelected(jobId)
    if (jobId) setCollapsed(true)
  }

  function openFolder(f: Folder | null) {
    if (f?.id !== folder?.id) setSelected(null)
    setFolder(f)
  }

  if (user === undefined) return null
  if (user === null) return <Login onLogin={setUser} />

  return (
    <>
      <header className="app-header">
        <span className="wordmark" aria-label="kvarn">
          <Wordmark />
        </span>
        <NavMenu tab={tab} onNavigate={setTab} />
        <span className="user">{user.name}</span>
        <button className="sign-out" onClick={signOut}>
          Logga ut
        </button>
      </header>

      <div className="app">
        {/* Hidden, not unmounted, so uploads keep going when switching tabs */}
        <main className="app-main collapsible" hidden={tab !== 'read'}>
          <Side collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} title="Visa samlingar och dokument">
            {folder ? (
              <FileQueue
                key={folder.id}
                folder={folder}
                onFolderChanged={openFolder}
                onBack={() => openFolder(null)}
                selected={selected}
                onSelect={openDocument}
                version={version}
              />
            ) : (
              <FolderList onOpen={openFolder} />
            )}
          </Side>
          {selected ? (
            <DocumentView jobId={selected} onChanged={() => setVersion((v) => v + 1)} />
          ) : (
            <div className="empty">{folder ? 'Välj ett dokument' : 'Välj eller skapa en samling'}</div>
          )}
        </main>
        {tab === 'templates' && (
          <main className="app-main">
            <TemplateEditor />
          </main>
        )}
        {tab === 'extract' && (
          <main className="app-main collapsible">
            <ExtractView />
          </main>
        )}
      </div>
    </>
  )
}
