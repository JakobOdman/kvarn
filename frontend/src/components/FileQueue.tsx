import { ArrowLeft, FileText, Pencil, Trash2, Upload } from 'lucide-react'
import { useEffect, useState } from 'react'
import {
  createJob,
  deleteFolder,
  deleteJob,
  getJob,
  listJobs,
  renameFolder,
  type Folder,
  type JobStatus,
  type JobSummary,
  type ReadSummary,
} from '../api'
import { readLabel, summarize } from '../labels'
import { Fold } from './Fold'
import { Toggle } from './Toggle'

async function downloadJson(jobId: string, name: string) {
  const { result } = await getJob(jobId)
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2) + '\n'], { type: 'application/json' }))
  a.download = name.replace(/\.[^.]+$/, '') + '.json'
  a.click()
  URL.revokeObjectURL(a.href)
}

interface Item {
  key: string
  name: string
  jobId?: string
  status: JobStatus
  summary?: ReadSummary
  options?: JobSummary['options']
  created?: string
  error?: string
}

const fromJob = (j: JobSummary): Item => ({
  key: j.job_id,
  name: j.name,
  jobId: j.job_id,
  status: j.status,
  summary: j.status === 'done' ? j.summary : undefined,
  options: j.options,
  created: j.created,
  error: j.error ?? undefined,
})

function describe(item: Item): string {
  if (item.error) return `Fel: ${item.error}`
  const s = item.summary
  if (item.status === 'queued') return 'Väntar…'
  if (item.status !== 'done' || !s) return 'Läser…'
  if (s.skipped) return 'Kunde inte läsas'
  const parts = [`${s.pages} av ${s.page_count} sidor`, `${s.model_pages} via AI`]
  if (s.partial) parts.push('ofullständig')
  return parts.join(' · ')
}

/** Every read document (saved in the database), newest first, and uploads of new ones.
 *  Calls onSelect when a finished document is clicked. */
export function FileQueue({
  folder,
  onFolderChanged,
  onBack,
  selected,
  onSelect,
  version,
}: {
  version: number // bumped when a document changed elsewhere, e.g. read again
  folder: Folder
  onFolderChanged: (folder: Folder | null) => void // renamed, or null when deleted
  onBack: () => void
  selected: string | null
  onSelect: (jobId: string | null) => void
}) {
  const [items, setItems] = useState<Item[]>([])
  const [noModel, setNoModel] = useState(true)
  const [words, setWords] = useState(false)
  const [newName, setNewName] = useState<string | null>(null) // the folder name while it is being edited

  useEffect(() => {
    // Saved documents from the server; uploads still on their way (no job id yet) stay on top
    listJobs(folder.id).then((jobs) => setItems((now) => [...now.filter((n) => !n.jobId), ...jobs.map(fromJob)]))
  }, [folder.id, version])

  async function saveName() {
    const name = newName?.trim()
    setNewName(null)
    if (name && name !== folder.name) onFolderChanged(await renameFolder(folder.id, name))
  }

  async function removeFolder() {
    if (
      !confirm(
        `Ta bort samlingen ${folder.name} och dess ${items.length} dokument? Extraktioner som redan gjorts finns kvar.`,
      )
    )
      return
    await deleteFolder(folder.id)
    onSelect(null)
    onFolderChanged(null)
  }

  const update = (key: string, changes: Partial<Item>) =>
    setItems((all) => all.map((i) => (i.key === key ? { ...i, ...changes } : i)))

  async function run(key: string, file: File) {
    try {
      const jobId = await createJob(file, { folderId: folder.id, noModel, maxModelPages: 0, words })
      update(key, { jobId, options: { allow_model: !noModel, words }, created: new Date().toISOString() })
      let job = await getJob(jobId)
      while (job.status === 'queued' || job.status === 'running') {
        update(key, { status: job.status })
        await new Promise((r) => setTimeout(r, 1000))
        job = await getJob(jobId)
      }
      update(key, {
        status: job.status,
        summary: job.result ? summarize(job.result) : undefined,
        error: job.error ?? undefined,
      })
    } catch (e) {
      update(key, { status: 'error', error: String(e) })
    }
  }

  async function remove(item: Item) {
    if (!confirm(`Ta bort ${item.name}? Läsningen försvinner, men extraktioner som redan gjorts finns kvar.`)) return
    await deleteJob(item.jobId!)
    setItems((all) => all.filter((i) => i.key !== item.key))
    if (item.jobId === selected) onSelect(null)
  }

  function addFiles(files: FileList) {
    const added = Array.from(files).map((file) => ({
      file,
      item: { key: crypto.randomUUID(), name: file.name, status: 'queued' as JobStatus },
    }))
    setItems((all) => [...added.map((a) => a.item), ...all])
    added.forEach((a) => run(a.item.key, a.file))
  }

  return (
    <section className="card">
      <button className="back" onClick={onBack}>
        <ArrowLeft /> Samlingar
      </button>
      <div className="folder-head">
        {newName === null ? (
          <h3>{folder.name}</h3>
        ) : (
          <input
            className="folder-name-input"
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') saveName()
              if (e.key === 'Escape') setNewName(null)
            }}
            onBlur={saveName}
          />
        )}
        <button title="Byt namn" onClick={() => setNewName(folder.name)}>
          <Pencil />
        </button>
        <button title="Ta bort samlingen" onClick={removeFolder}>
          <Trash2 />
        </button>
      </div>
      <div className="toggles">
        <Toggle
          label="AI-läsning"
          description="Skannade sidor och bilder läses av AI."
          badge={<span className="cost">Kostar</span>}
          checked={!noModel}
          onChange={(on) => setNoModel(!on)}
        />
        <Toggle
          label="Ordpositioner"
          description="Sparar var varje ord står, så de kan markeras i originalet."
          checked={words}
          onChange={setWords}
        />
      </div>
      <label className="dropzone">
        <input
          type="file"
          multiple
          onChange={(e) => {
            if (e.target.files) addFiles(e.target.files)
            e.target.value = ''
          }}
        />
        <Upload />
        <span>Välj filer</span>
      </label>
      <Fold title="Dokument" summary={documentSummary(items)}>
        <ul className="queue">
          {items.map((item) => {
            const done = item.status === 'done' && item.jobId
            return (
              <li
                key={item.key}
                className={`${done ? 'done' : ''} ${item.jobId === selected ? 'selected' : ''}`}
                onClick={() => done && onSelect(item.jobId!)}
              >
                <span className="icon">
                  <FileText />
                  <span className={`dot ${item.summary?.skipped ? 'warn' : item.status}`} />
                </span>
                <div>
                  <div className="queue-name">{item.name}</div>
                  <div className="queue-meta">{describe(item)}</div>
                  {item.options && item.created && (
                    <div className="queue-meta faint">{readLabel({ options: item.options, created: item.created })}</div>
                  )}
                  {item.jobId && (item.status === 'done' || item.status === 'error') && (
                    <div className="item-actions">
                      {item.status === 'done' && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            downloadJson(item.jobId!, item.name)
                          }}
                        >
                          Ladda ner JSON
                        </button>
                      )}
                      <button
                        title="Ta bort"
                        onClick={(e) => {
                          e.stopPropagation()
                          remove(item)
                        }}
                      >
                        <Trash2 />
                      </button>
                    </div>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      </Fold>
    </section>
  )
}

/** "10" or "10 · 2 läses" */
function documentSummary(items: Item[]) {
  const reading = items.filter((i) => i.status === 'queued' || i.status === 'running').length
  return reading ? `${items.length} · ${reading} läses` : String(items.length)
}
