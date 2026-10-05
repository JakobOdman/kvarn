import { FileText, Table2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import {
  createExtraction,
  downloadXlsx,
  getExtraction,
  listExtractions,
  listFolders,
  listJobs,
  listTemplates,
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
  const [collapsed, setCollapsed] = useState(false) // the left column folded in, so the result gets the width

  useEffect(() => {
    listTemplates().then((t) => {
      setTemplates(t)
      if (t.length) setTemplateId((id) => id || t[0].id)
    })
    listFolders().then((f) => {
      setFolders(f)
      if (f.length) setFolderId((id) => id || f[0].id)
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

  async function openEarlier(id: string) {
    setError(null)
    setExtractionId(id)
    setExtraction(await getExtraction(id))
    setCollapsed(true)
  }

  async function run(asPaid: boolean) {
    if (asPaid && !confirm(`Skicka ${checked.size} dokument till AI:n? Det kostar pengar (cachade svar är gratis).`))
      return
    setError(null)
    try {
      const id = await createExtraction(templateId, folderId, [...checked], asPaid)
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
            <select value={folderId} onChange={(e) => setFolderId(e.target.value)}>
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
              {history.map((h) => {
                const rows = Object.values(h.row_counts).reduce((a, b) => a + b, 0)
                return (
                  <li
                    key={h.id}
                    className={`done ${h.id === extractionId ? 'selected' : ''}`}
                    onClick={() => openEarlier(h.id)}
                  >
                    <span className="icon">
                      <Table2 />
                      <span className={`dot ${h.documents.some((d) => d.error) ? 'warn' : h.status}`} />
                    </span>
                    <div>
                      <div className="queue-name">{h.folder_name ?? 'Utan samling'}</div>
                      <div className="queue-meta">
                        {h.template_name} · {h.documents.length} dokument · {rows} rader
                      </div>
                      <div className="queue-meta faint">{formatTime(h.created)}</div>
                    </div>
                  </li>
                )
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
              <p className="result-folder">{template.name}</p>
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
          {running && <Progress extraction={extraction} />}
          {!running && <Checks checks={extraction.checks ?? []} />}
          <ResultTables key={extraction.id} template={template} extraction={extraction} />
        </div>
      )}
    </>
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
