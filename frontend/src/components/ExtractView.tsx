import { FileText, Table2, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import {
  createExtraction,
  deleteExtraction,
  downloadXlsx,
  getExtraction,
  listExtractions,
  listFolders,
  listJobs,
  listTemplates,
  restartLiveExtraction,
  getConfig,
  type Extraction,
  type ExtractionSummary,
  type Folder,
  type JobSummary,
  type Template,
} from '../api'
import { formatTime, formatTokens, readLabel } from '../labels'
import { Checks } from './Checks'
import { Fold } from './Fold'
import { Progress } from './Progress'
import { ResultTables } from './ResultTables'
import { Side } from './Side'

/** Choose a folder and a template, run, see the rows. Earlier runs can be opened again. */
export function ExtractView() {
  const [folders, setFolders] = useState<Folder[]>([])
  const [folderId, setFolderId] = useState('')
  const [templates, setTemplates] = useState<Template[]>([])
  const [jobs, setJobs] = useState<JobSummary[]>([])
  const [paid, setPaid] = useState(false)
  const [spending, setSpending] = useState<{ spent: number; budget: number } | null>(null)
  const [templateId, setTemplateId] = useState('')
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [extractionId, setExtractionId] = useState<string | null>(null)
  const [extraction, setExtraction] = useState<Extraction | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [history, setHistory] = useState<ExtractionSummary[]>([])
  const [expanded, setExpanded] = useState<Set<string>>(new Set()) // groups showing their older runs
  const [collapsed, setCollapsed] = useState(false) // the left column folded in, so the result gets the width

  useEffect(() => {
    listTemplates().then((t) => {
      setTemplates(t)
      if (t.length) setTemplateId((id) => id || t[0].id)
    })
    listFolders().then((f) => {
      setFolders(f)
      if (f.length) chooseFolder(f[0])
    })
    getConfig().then((c) => {
      setPaid(c.paid)
      setSpending(c)
    })
    listExtractions().then(setHistory)
  }, [])

  // The folder's read documents, all ticked: untick one to leave it out
  useEffect(() => {
    if (!folderId) return
    listJobs(folderId).then((all) => {
      const read = all.filter((j) => j.status === 'done' && j.ok)
      setJobs(read)
      setChecked(new Set(read.map((j) => j.job_id)))
    })
  }, [folderId])

  /** The folder's own template, if it has one, is chosen with it. */
  function chooseFolder(folder: Folder) {
    setFolderId(folder.id)
    if (folder.template_id) setTemplateId(folder.template_id)
  }

  async function openEarlier(id: string) {
    setError(null)
    setCollapsed(true)
    await follow(id)
  }

  /** Show the extraction, and keep it up to date while it runs. */
  async function follow(id: string) {
    setExtractionId(id)
    let e = await getExtraction(id)
    while (e.status === 'queued' || e.status === 'running') {
      setExtraction(e)
      await new Promise((r) => setTimeout(r, 1000))
      e = await getExtraction(id)
    }
    setExtraction(e)
    setHistory(await listExtractions())
    setSpending(await getConfig())
  }

  async function runAgain(e: Extraction) {
    if (!confirm('Köra om alla dokument i samlingen med mallen som den är nu? Det kostar.')) return
    setError(null)
    try {
      const { extraction_id } = await restartLiveExtraction(e.folder_id!)
      if (extraction_id) await follow(extraction_id)
      else setHistory(await listExtractions())
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function removeEarlier(h: ExtractionSummary) {
    if (!confirm(`Ta bort körningen från ${formatTime(h.created)}? Raderna försvinner.`)) return
    await deleteExtraction(h.id)
    if (h.id === extractionId) {
      setExtractionId(null)
      setExtraction(null)
    }
    setHistory(await listExtractions())
  }

  function toggleOlder(key: string) {
    const next = new Set(expanded)
    if (!next.delete(key)) next.add(key)
    setExpanded(next)
  }

  async function run(asPaid: boolean) {
    if (asPaid && !confirm(`Skicka ${checked.size} dokument till AI:n? Det kostar pengar (cachade svar är gratis).`))
      return
    setError(null)
    try {
      const id = await createExtraction(templateId, folderId, [...checked], asPaid)
      await follow(id)
      setCollapsed(true)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const toggle = (id: string) =>
    setChecked((s) => {
      const next = new Set(s)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const template = extraction?.template
  const extractionFolder = folders.find((f) => f.id === extraction?.folder_id)
  const counted = extraction?.documents.filter((d) => d.tokens_in !== undefined) ?? []
  const tokensIn = counted.reduce((sum, d) => sum + (d.tokens_in ?? 0), 0)
  const tokensOut = counted.reduce((sum, d) => sum + (d.tokens_out ?? 0), 0)
  const allCached = counted.length > 0 && counted.every((d) => d.cached)
  const running = extraction?.status === 'queued' || extraction?.status === 'running'
  const canRun = templateId && checked.size > 0 && !running

  return (
    <>
      <Side collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} title="Visa samling och mall">
        <section className="card extract-setup">
          <span className="caps">Samling</span>
          {folders.length ? (
            <select value={folderId} onChange={(e) => chooseFolder(folders.find((f) => f.id === e.target.value)!)}>
              {folders.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
          ) : (
            <p className="queue-meta">Inga samlingar än. Skapa en under Läsa.</p>
          )}

          <span className="caps">Mall</span>
          {templates.length ? (
            <select value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          ) : (
            <p className="queue-meta">Inga mallar än. Skapa en under Mallar.</p>
          )}

          {jobs.length ? (
            <Fold key={folderId} title="Dokument" summary={`${checked.size} av ${jobs.length}`}>
              <div className="options">
                {jobs.map((j) => (
                  <label key={j.job_id}>
                    <input type="checkbox" checked={checked.has(j.job_id)} onChange={() => toggle(j.job_id)} />
                    <span>
                      {j.name}
                      <span className="queue-meta faint">{readLabel(j)}</span>
                    </span>
                  </label>
                ))}
              </div>
            </Fold>
          ) : (
            <p className="queue-meta">Inga lästa dokument i samlingen. Läs dokument under Läsa först.</p>
          )}

          <button disabled={!canRun} onClick={() => run(false)}>
            {running ? 'Kör…' : 'Kör'}
          </button>
          {paid && (
            <button className="primary" disabled={!canRun} onClick={() => run(true)}>
              {running ? 'Kör…' : 'Kör (betalt)'}
            </button>
          )}
          <p className="engine-note">
            {paid
              ? 'Kör använder bara sparade svar. Kör (betalt) skickar resten till AI:n.'
              : 'Utvecklingsläge: sparade svar eller tomt testsvar. Inget skickas till AI:n.'}
          </p>
          {paid && spending && (
            <p className="engine-note">
              AI denna månad: {spending.spent.toFixed(2)} av {spending.budget.toFixed(0)} USD
            </p>
          )}
          {error && <p className="read-warning">{error}</p>}

          {extraction && (
            <Fold
              key={`${extraction.id}-${extraction.documents.some((d) => d.error)}`} // opens when an error turns up
              title="Körningen"
              summary={runSummary(extraction)}
              startOpen={extraction.documents.some((d) => d.error)}
            >
              <ul className="queue">
                {extraction.documents.map((d) => (
                  <li key={d.job_id}>
                    <span className="icon">
                      <FileText />
                      <span className={`dot ${d.status}`} />
                    </span>
                    <div>
                      <div className="queue-name">{d.name}</div>
                      {d.error && <div className="queue-meta">{d.error}</div>}
                      {d.tokens_in !== undefined && (
                        <div className="queue-meta faint">
                          {formatTokens(d.tokens_in, d.tokens_out ?? 0)}
                          {d.cached && ' (sparat svar)'}
                        </div>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </Fold>
          )}
        </section>

        {history.length > 0 && (
          <section className="card">
            <span className="caps">Tidigare körningar</span>
            <ul className="queue">
              {groupRuns(history).map(([latest, ...older]) => {
                const key = latest.live ? `live/${latest.id}` : `${latest.folder_id}/${latest.template_id}`
                const open = expanded.has(key)
                return [
                  <EarlierRun
                    key={latest.id}
                    run={latest}
                    selected={latest.id === extractionId}
                    onOpen={() => openEarlier(latest.id)}
                    onRemove={() => removeEarlier(latest)}
                    older={older.length}
                    olderOpen={open}
                    onToggleOlder={() => toggleOlder(key)}
                  />,
                  ...(open
                    ? older.map((h) => (
                        <EarlierRun
                          key={h.id}
                          run={h}
                          older={0}
                          selected={h.id === extractionId}
                          onOpen={() => openEarlier(h.id)}
                          onRemove={() => removeEarlier(h)}
                        />
                      ))
                    : []),
                ]
              })}
            </ul>
          </section>
        )}
      </Side>

      {!extraction || !template ? (
        <div className="empty">Välj samling och mall</div>
      ) : (
        <div className="card results">
          <div className="document-head">
            <div>
              <h2>{extractionFolder?.name ?? 'Utan samling'}</h2>
              <p className="result-folder">
                {template.name}
                {extraction.live && ' · aktuell tabell'}
              </p>
              {counted.length > 0 && (
                <p className="result-tokens">
                  {formatTokens(tokensIn, tokensOut)} tokens{allCached && ' · sparade svar, ingen kostnad'}
                </p>
              )}
            </div>
            {!running && (
              <button onClick={() => downloadXlsx(extractionId!, template.id)}>Ladda ner Excel</button>
            )}
          </div>
          {extraction.template_changed && !running && (
            <div className="read-warning live-changed">
              <span>Mallen har ändrats sedan körningen startade. Nya dokument körs fortfarande med den gamla.</span>
              <button onClick={() => runAgain(extraction)}>Kör om alla</button>
            </div>
          )}
          {running && <Progress extraction={extraction} />}
          {!running && <Checks checks={extraction.checks ?? []} />}
          <ResultTables key={extraction.id} template={template} extraction={extraction} />
        </div>
      )}
    </>
  )
}

/** The runs grouped by folder and template, newest first in each group (the list comes newest first). */
function groupRuns(runs: ExtractionSummary[]): ExtractionSummary[][] {
  const groups = new Map<string, ExtractionSummary[]>()
  for (const r of [...runs.filter((r) => r.live), ...runs.filter((r) => !r.live)]) {
    const key = r.live ? `live/${r.id}` : `${r.folder_id}/${r.template_id}` // a live run is a group of its own, first
    groups.set(key, [...(groups.get(key) ?? []), r])
  }
  return [...groups.values()]
}

/** One earlier run in the list. The newest of a group also opens its older runs. */
function EarlierRun({ run, selected, onOpen, onRemove, older, olderOpen, onToggleOlder }: {
  run: ExtractionSummary
  selected: boolean
  onOpen: () => void
  onRemove: () => void
  older: number
  olderOpen?: boolean
  onToggleOlder?: () => void
}) {
  const rows = Object.values(run.row_counts).reduce((a, b) => a + b, 0)
  const isOlder = !onToggleOlder
  return (
    <li className={`done ${selected ? 'selected' : ''} ${isOlder ? 'older' : ''}`} onClick={onOpen}>
      <span className="icon">
        <Table2 />
        <span className={`dot ${run.documents.some((d) => d.error) ? 'warn' : run.status}`} />
      </span>
      <div>
        {!isOlder && (
          <div className="queue-name">
            {run.folder_name ?? 'Utan samling'}
            {run.live && <span className="live-badge">Aktuell</span>}
          </div>
        )}
        <div className="queue-meta">
          {!isOlder && `${run.template_name} · `}
          {run.documents.length} dokument · {rows} rader
        </div>
        <div className="queue-meta faint">{formatTime(run.created)}</div>
        <div className="item-actions">
          {older > 0 && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onToggleOlder?.()
              }}
            >
              {olderOpen ? 'Dölj' : older === 1 ? '1 tidigare' : `${older} tidigare`}
            </button>
          )}
          <button
            title="Ta bort körningen"
            onClick={(e) => {
              e.stopPropagation()
              onRemove()
            }}
          >
            <Trash2 />
          </button>
        </div>
      </div>
    </li>
  )
}

/** "8 klara · 1 fel · 1 kvar" */
function runSummary(extraction: Extraction) {
  const count = (status: string) => extraction.documents.filter((d) => d.status === status).length
  const left = extraction.documents.length - count('done') - count('error')
  return [
    `${count('done')} klara`,
    count('error') > 0 && `${count('error')} fel`,
    left > 0 && `${left} kvar`,
  ].filter(Boolean).join(' · ')
}
