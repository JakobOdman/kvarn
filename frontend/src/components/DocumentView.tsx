import { useEffect, useState } from 'react'
import { fileUrl, getJob, rereadWithAi, type Job } from '../api'
import { missingPages, READERS, warning } from '../labels'
import { PdfPages } from './PdfPages'

/** The extracted text, what happened during the read, and the original on demand. */
export function DocumentView({ jobId, onChanged }: { jobId: string; onChanged: () => void }) {
  const [job, setJob] = useState<Job | null>(null)
  const [showOriginal, setShowOriginal] = useState(false)
  const [fileSrc, setFileSrc] = useState<string | null>(null) // the original as a blob: URL, fetched when shown

  useEffect(() => {
    setJob(null)
    getJob(jobId).then(setJob)
  }, [jobId])

  useEffect(() => {
    if (!showOriginal) return
    let url: string | null = null
    fileUrl(jobId).then((u) => setFileSrc((url = u)))
    return () => {
      setFileSrc(null)
      if (url) URL.revokeObjectURL(url)
    }
  }, [jobId, showOriginal])

  async function rereadAi() {
    if (!confirm('Läsa om dokumentet med AI-läsning? Det kostar per sida som läses av AI.')) return
    await rereadWithAi(jobId)
    onChanged()
    let j = await getJob(jobId)
    while (j.status === 'queued' || j.status === 'running') {
      setJob(j)
      await new Promise((r) => setTimeout(r, 1500))
      j = await getJob(jobId)
    }
    setJob(j)
    onChanged()
  }

  if (job && !job.result && (job.status === 'queued' || job.status === 'running'))
    return (
      <div className="card document">
        <h2>{job.name}</h2>
        <div className="progress">
          <div className="progress-text">Läser om med AI-läsning…</div>
          <div className="progress-track">
            <div className="progress-current" style={{ left: 0, width: '100%' }} />
          </div>
        </div>
      </div>
    )
  if (!job?.result) return null
  const result = job.result
  const { mime_type, pages } = result
  const pdf = mime_type === 'application/pdf'
  const canShow = pdf || mime_type.startsWith('image/')
  const hasWords = pages.some((p) => p.words?.length)
  const missing = missingPages(result)
  const warn = warning(result)

  return (
    <div className="card document">
      <div className="document-head">
        <h2>{job.name}</h2>
        {canShow && (
          <button onClick={() => setShowOriginal(!showOriginal)}>
            {showOriginal ? 'Dölj original' : 'Visa original'}
          </button>
        )}
      </div>

      <div className="read-info">
        <span className="caps">Om läsningen</span>
        {result.ok && (
          <p>
            {mime_type} · {READERS[result.reader] ?? result.reader} · {pages.length} av {result.page_count} sidor
            lästa
          </p>
        )}
        {warn && <p className="read-warning">{warn}</p>}
        {(result.partial === 'ai_gated' || result.skipped === 'ai_gated') && (
          <button className="primary reread" onClick={rereadAi}>
            Läs om med AI-läsning
          </button>
        )}
        {missing.length > 0 && <p>Saknade sidor: {missing.join(', ')}</p>}
      </div>

      <div className={`document-body ${showOriginal ? 'split' : ''}`}>
        {showOriginal && fileSrc && (
          <div className="document-original">
            {pdf && hasWords && <PdfPages url={fileSrc} pages={pages} />}
            {pdf && !hasWords && <iframe src={fileSrc} title={job.name} />}
            {mime_type.startsWith('image/') && <img src={fileSrc} alt={job.name} />}
          </div>
        )}
        {pages.length > 0 && (
          <div className="document-text">
            {pages.map((p, i) => (
              <section key={p.page_no}>
                <span className="caps">
                  Sida {p.page_no} · {READERS[p.reader] ?? p.reader}
                </span>
                <pre>{job.layout?.[i] ?? p.text}</pre>
              </section>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
