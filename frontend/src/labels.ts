import type { JobSummary, ReadResult, ReadSummary } from './api'

export const READERS: Record<string, string> = {
  pdf_text: 'Textlager',
  claude_vision: 'AI',
  office: 'Office',
  text: 'Text',
  html: 'HTML',
}

const PARTIAL: Record<string, string> = {
  ai_gated: 'Vissa sidor är skannade eller bilder och kan bara läsas med AI-läsning, som var avstängd.',
  budget: 'Taket för antal modellsidor nåddes, så alla sidor lästes inte.',
  ai_unconfigured: 'Modellen är inte konfigurerad (API-nyckel saknas), så vissa sidor lästes inte.',
}

const SKIPPED: Record<string, string> = {
  ai_gated: 'Dokumentet saknar textlager och kan bara läsas med AI-läsning, som var avstängd.',
  empty: 'Ingen text hittades i dokumentet.',
  unsupported_mime: 'Filtypen stöds inte.',
  structured: 'Strukturerad data (t.ex. JSON eller CSV) läses inte.',
  ai_unconfigured: 'Modellen är inte konfigurerad (API-nyckel saknas).',
}

/** Plain-language warning for an incomplete or failed read, or null if all is well. */
export function warning(result: ReadResult): string | null {
  if (result.skipped) return SKIPPED[result.skipped] ?? `Hoppades över: ${result.skipped}`
  if (result.partial) return PARTIAL[result.partial] ?? `Ofullständig: ${result.partial}`
  return null
}

/** Page numbers that are in the document but not in the result. */
export function missingPages(result: ReadResult): number[] {
  const read = new Set(result.pages.map((p) => p.page_no))
  return Array.from({ length: result.page_count }, (_, i) => i + 1).filter((n) => !read.has(n))
}

export function summarize(result: ReadResult): ReadSummary {
  return {
    page_count: result.page_count,
    pages: result.pages.length,
    model_pages: result.pages.filter((p) => p.reader === 'claude_vision').length,
    partial: result.partial,
    skipped: result.skipped,
  }
}

const n = (x: number) => x.toLocaleString('sv-SE')

/** "27 850 in · 4 205 ut" */
export const formatTokens = (tokensIn: number, tokensOut: number) => `${n(tokensIn)} in · ${n(tokensOut)} ut`

export const formatTime = (iso: string) =>
  new Date(iso).toLocaleString('sv-SE', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

/** "Textlager · 4 okt 14:02" - tells two reads of the same file apart. */
export function readLabel(job: Pick<JobSummary, 'options' | 'created'>): string {
  const mode = job.options.allow_model ? 'AI-läsning' : 'Textlager'
  return `${mode} · ${formatTime(job.created)}`
}
