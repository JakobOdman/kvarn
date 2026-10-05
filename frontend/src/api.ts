import { supabase } from './supabase'

/** fetch to the backend (everything under /api) with the logged-in user's Supabase token,
 *  which the backend checks on every call. */
async function apiFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const { data } = await supabase.auth.getSession() // refreshes the token when it is about to expire
  const headers = new Headers(init.headers)
  if (data.session) headers.set('Authorization', `Bearer ${data.session.access_token}`)
  return fetch(`/api${url}`, { ...init, headers })
}

/** A file from the backend as a local blob: URL, for <img>, <iframe> and pdf.js, which cannot send the token. */
async function blobUrl(url: string): Promise<string> {
  const res = await apiFetch(url)
  if (!res.ok) throw new Error(await errorText(res))
  return URL.createObjectURL(await res.blob())
}

export type JobStatus = 'queued' | 'running' | 'done' | 'error'

export interface Options {
  folderId: string
  noModel: boolean
  maxModelPages: number
  model?: string
  words: boolean
}

export interface Page {
  page_no: number
  text: string
  reader: string
  has_text_layer: boolean
  page_width: number | null
  page_height: number | null
  words?: WordBox[] | null
}

/** A word and its box in page units, origin top-left. */
export interface WordBox {
  t: string
  x0: number
  y0: number
  x1: number
  y1: number
}

export interface ReadResult {
  ok: boolean
  mime_type: string
  pages: Page[]
  reader: string
  page_count: number
  partial: string | null
  skipped: string | null
}

export interface Job {
  status: JobStatus
  name: string
  error: string | null
  result: ReadResult | null
  layout: string[] | null // each page's text in reading order, what the AI gets
}

/** The file's sha256 as hex: its name in storage, and how the backend checks it arrived whole. */
async function sha256Hex(file: File): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('')
}

type UploadTarget = { kind: 'supabase'; path: string; token: string } | { kind: 'local'; url: string }

/** Upload the file straight to storage (Supabase, or the backend locally), then start reading it.
 *  Returns the job_id. */
export async function createJob(file: File, options: Options): Promise<string> {
  const sha256 = await sha256Hex(file)
  const target: UploadTarget = await sendJson('/uploads', 'POST', { folder_id: options.folderId, sha256 })
  if (target.kind === 'supabase') {
    const { error } = await supabase.storage.from('filer').uploadToSignedUrl(target.path, target.token, file, {
      upsert: true,
    })
    if (error) throw new Error(`Uppladdningen misslyckades: ${error.message}`)
  } else {
    const res = await apiFetch(target.url, { method: 'PUT', body: file })
    if (!res.ok) throw new Error(await errorText(res))
  }
  const job = await sendJson('/jobs', 'POST', {
    folder_id: options.folderId,
    name: file.name,
    sha256,
    no_model: options.noModel,
    max_model_pages: options.maxModelPages,
    words: options.words,
    ...(options.model && { model: options.model }),
  })
  return job.job_id
}

/** GET /jobs/{id} */
export async function getJob(jobId: string): Promise<Job> {
  const res = await apiFetch(`/jobs/${jobId}`)
  if (!res.ok) throw new Error(`Could not get job: ${res.status}`)
  return res.json()
}

/** Read the saved file again with AI reading on. Costs money. */
export async function rereadWithAi(jobId: string): Promise<void> {
  const res = await apiFetch(`/jobs/${jobId}/reread?ai=true`, { method: 'POST' })
  if (!res.ok) throw new Error(await errorText(res))
}

export async function deleteJob(jobId: string): Promise<void> {
  const res = await apiFetch(`/jobs/${jobId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await errorText(res))
}

/** The original file as a blob: URL, for showing it in the document view. Revoke it when done. */
export const fileUrl = (jobId: string): Promise<string> => blobUrl(`/jobs/${jobId}/file`)

// --- Step 2: templates ---

export interface TemplateField {
  name: string
  description: string
  type: 'text' | 'integer' | 'choice'
  choices: string[]
}

export interface TemplateTable {
  name: string
  description: string
  fields: TemplateField[]
}

/** A check counted after the extraction, per document (api/checks.py). */
export interface Rule {
  type: 'sum' | 'count' | 'required' | 'unique'
  table: string
  field: string // not used by count
  target_table: string // sum and count: what the rows are compared with
  target_field: string
}

export interface Template {
  id: string
  name: string
  prompt: string
  tables: TemplateTable[]
  page_selection: boolean
  rules: Rule[]
}

/** FastAPI errors come as {detail: "..."} or, for validation, {detail: [{msg}, ...]}. */
async function errorText(res: Response): Promise<string> {
  try {
    const { detail } = await res.json()
    if (Array.isArray(detail)) return detail.map((d) => d.msg.replace(/^Value error, /, '')).join(' ')
    return String(detail)
  } catch {
    return `Fel ${res.status}`
  }
}

export async function listTemplates(): Promise<Template[]> {
  const res = await apiFetch('/templates')
  if (!res.ok) throw new Error(await errorText(res))
  return res.json()
}

/** Create or update. Returns the template with its id. */
export async function saveTemplate(template: Template): Promise<Template> {
  const res = await apiFetch('/templates', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(template),
  })
  if (!res.ok) throw new Error(await errorText(res))
  return res.json()
}

export async function deleteTemplate(id: string): Promise<void> {
  const res = await apiFetch(`/templates/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await errorText(res))
}

// --- Step 2: extraction ---

export interface ReadSummary {
  page_count: number | null
  pages: number | null
  model_pages: number | null
  partial: string | null
  skipped: string | null
}

/** A read document in the list: a summary instead of the whole result. */
export interface JobSummary {
  job_id: string
  name: string
  folder_id: string
  status: JobStatus
  error: string | null
  ok: boolean
  created: string
  options: { allow_model: boolean; words: boolean }
  summary: ReadSummary
}

export interface Extraction {
  id: string
  status: JobStatus
  template_id: string
  template: Template // as it was when the extraction ran
  folder_id: string | null
  created: string
  documents: {
    job_id: string
    name: string
    status: JobStatus
    error: string | null
    tokens_in?: number
    tokens_out?: number
    cached?: boolean // the answer came from the cache: no cost this time
  }[]
  tables: Record<string, Record<string, string | number | null>[]>
  checks: Check[]
}

/** A rule counted on one document (api/checks.py). rows are indexes in tables[table]. */
export interface Check {
  rule: number
  description: string
  table: string
  document: string
  status: 'ok' | 'fail' | 'unknown'
  message: string
  rows: number[]
}

/** An earlier run in the list: row counts instead of the rows. */
export interface ExtractionSummary {
  id: string
  template_id: string
  template_name: string
  created: string
  status: JobStatus
  documents: Extraction['documents']
  folder_id: string | null
  folder_name: string | null
  row_counts: Record<string, number>
}

export async function listExtractions(): Promise<ExtractionSummary[]> {
  const res = await apiFetch('/extractions')
  if (!res.ok) throw new Error(await errorText(res))
  return res.json()
}

/** All read documents, or one folder's. */
export async function listJobs(folderId?: string): Promise<JobSummary[]> {
  const res = await apiFetch(folderId ? `/jobs?folder_id=${folderId}` : '/jobs')
  if (!res.ok) throw new Error(await errorText(res))
  return res.json()
}

export async function paidAllowed(): Promise<boolean> {
  const res = await apiFetch('/config')
  return res.ok && (await res.json()).paid
}

/** POST /extractions - returns the extraction_id. */
export async function createExtraction(
  templateId: string,
  folderId: string,
  jobIds: string[],
  paid: boolean,
): Promise<string> {
  const res = await apiFetch('/extractions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ template_id: templateId, folder_id: folderId, job_ids: jobIds, paid }),
  })
  if (!res.ok) throw new Error(await errorText(res))
  return (await res.json()).extraction_id
}

export async function getExtraction(id: string): Promise<Extraction> {
  const res = await apiFetch(`/extractions/${id}`)
  if (!res.ok) throw new Error(await errorText(res))
  return res.json()
}

/** Download all tables as one Excel file. */
export async function downloadXlsx(id: string, name: string): Promise<void> {
  const url = await blobUrl(`/extractions/${id}/xlsx`)
  const a = document.createElement('a')
  a.href = url
  a.download = `${name}.xlsx`
  a.click()
  URL.revokeObjectURL(url)
}

// --- Folders ---

export interface Folder {
  id: string
  name: string
  created: string
  document_count: number
}

async function sendJson(url: string, method: string, body?: unknown) {
  const res = await apiFetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await errorText(res))
  return res.json()
}

export async function listFolders(): Promise<Folder[]> {
  const res = await apiFetch('/folders')
  if (!res.ok) throw new Error(await errorText(res))
  return res.json()
}

export const createFolder = (name: string): Promise<Folder> => sendJson('/folders', 'POST', { name })
export const renameFolder = (id: string, name: string): Promise<Folder> => sendJson(`/folders/${id}`, 'PATCH', { name })
export const deleteFolder = (id: string): Promise<void> => sendJson(`/folders/${id}`, 'DELETE')

// --- Login ---

export interface User {
  email: string
  name: string
}

/** The logged-in user, or null when not logged in. */
export async function me(): Promise<User | null> {
  const { data } = await supabase.auth.getSession()
  if (!data.session) return null
  const res = await apiFetch('/me')
  return res.ok ? res.json() : null
}

/** Log in with Supabase, then ask the backend who that is. */
export async function login(email: string, password: string): Promise<User> {
  const { error } = await supabase.auth.signInWithPassword({ email, password })
  if (error) throw new Error(error.message === 'Invalid login credentials' ? 'Fel e-post eller lösenord.' : error.message)
  const user = await me()
  if (!user) throw new Error('Inloggad hos Supabase, men Kvarn känner inte igen kontot.')
  return user
}

export async function logout(): Promise<void> {
  await supabase.auth.signOut()
}
