import { useEffect, useRef, useState } from 'react'
import * as pdfjs from 'pdfjs-dist'
import type { PDFDocumentProxy } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import type { Page } from '../api'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

const pct = (n: number) => `${n * 100}%`

function PdfPage({ doc, page }: { doc: PDFDocumentProxy; page: Page }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const { page_width: w, page_height: h } = page

  useEffect(() => {
    let cancel = () => {}
    doc.getPage(page.page_no).then((p) => {
      const viewport = p.getViewport({ scale: 1.5 })
      const c = canvas.current
      if (!c) return
      c.width = viewport.width
      c.height = viewport.height
      const task = p.render({ canvas: c, viewport })
      task.promise.catch(() => {}) // cancelled when the page unmounts
      cancel = () => task.cancel()
    })
    return () => cancel()
  }, [doc, page.page_no])

  return (
    <div className="pdf-page">
      <canvas ref={canvas} />
      {w && h &&
        page.words?.map((word, i) => (
          <span
            key={i}
            className="word"
            title={word.t}
            style={{
              left: pct(word.x0 / w),
              top: pct(word.y0 / h),
              width: pct((word.x1 - word.x0) / w),
              height: pct((word.y1 - word.y0) / h),
            }}
          />
        ))}
    </div>
  )
}

/** Every page of a PDF drawn with pdf.js, with the word boxes on top. */
export function PdfPages({ url, pages }: { url: string; pages: Page[] }) {
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null)

  useEffect(() => {
    const task = pdfjs.getDocument({ url })
    task.promise.then(setDoc).catch(() => {})
    return () => {
      setDoc(null)
      task.destroy()
    }
  }, [url])

  if (!doc) return null
  return (
    <div className="pdf-pages">
      {pages.map((p) => (
        <PdfPage key={p.page_no} doc={doc} page={p} />
      ))}
    </div>
  )
}
