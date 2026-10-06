import { ArrowDown, ArrowUp, ChevronDown, Table2 } from 'lucide-react'
import { useRef, useState } from 'react'
import type { Extraction, Template, TemplateField, TemplateTable } from '../api'

type Row = Extraction['tables'][string][number]

const label = (name: string) => name.charAt(0).toUpperCase() + name.slice(1).replace(/_/g, ' ')

// "22,401,237", "(300)", "10.8%" - right-aligned with even digits
// A dash in an amount column means the value is missing, not that the column is text
const isEmpty = (v: unknown) => v === null || v === '' || (typeof v === 'string' && /^[-–]$/.test(v.trim()))

const isNumber = (v: unknown) =>
  typeof v === 'number' || (typeof v === 'string' && /^[(\-–−]?[\d\s.,]+%?\)?$/.test(v.trim()) && /\d/.test(v))

/** "12 500,5", "1,234.5", "(300)", "10.8%" -> number, like toNumber in checks.py. null when it is not one. */
function toNumber(v: unknown): number | null {
  if (typeof v === 'number') return v
  if (typeof v !== 'string' || !isNumber(v)) return null
  let s = v.trim()
  const negative = /^\(.*\)$/.test(s) || /^[-–−]/.test(s)
  s = s.replace(/[()%\s\-–−]/g, '')
  if (s.includes(',') && s.includes('.')) s = s.lastIndexOf(',') > s.lastIndexOf('.') ? s.replace(/\./g, '').replace(',', '.') : s.replace(/,/g, '')
  else if ((s.match(/[.,]/g) ?? []).length > 1) s = s.replace(/[.,]/g, '')
  else if (/^\d+,\d{3}$/.test(s)) s = s.replace(',', '') // 1,234 is a thousand separator
  else s = s.replace(',', '.')
  const n = Number(s)
  return Number.isNaN(n) ? null : negative ? -n : n
}

const numberFormat = new Intl.NumberFormat('sv-SE', { maximumFractionDigits: 3 })

function Value({ field, value, numeric }: { field: TemplateField; value: Row[string]; numeric: boolean }) {
  if (value === null || value === '') return <span className="none">–</span>
  if (field.type === 'choice') return <span className="badge">{value}</span>
  const n = numeric ? toNumber(value) : null
  if (n !== null) return <>{numberFormat.format(n)}{String(value).trim().endsWith('%') ? ' %' : ''}</>
  return <>{value}</>
}

/** "06.2, Övergripande tjänstekrav 2026-04-13.pdf" -> "06.2, Övergripande tjänstekrav 2026-04-13" */
const shortName = (name: string) => name.replace(/\.(pdf|docx?|xlsx?|pptx?|txt|png|jpe?g|heic)$/i, '')

type Sort = { column: string; dir: 1 | -1 } | null

/** Numbers as numbers, text in Swedish order with 2 before 10, empty values last whichever way. */
function sortRows(rows: Row[], sort: Sort, numeric: Set<string>): Row[] {
  if (!sort) return rows
  const key = (r: Row) => (numeric.has(sort.column) ? toNumber(r[sort.column]) : r[sort.column])
  return [...rows].sort((a, b) => {
    const x = key(a)
    const y = key(b)
    if (isEmpty(x) || x === undefined) return isEmpty(y) || y === undefined ? 0 : 1
    if (isEmpty(y) || y === undefined) return -1
    const order =
      typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y), 'sv', { numeric: true })
    return order * sort.dir
  })
}

function downloadCsv(name: string, columns: string[], rows: Row[]) {
  const cell = (v: unknown) => `"${String(v ?? '').replace(/"/g, '""')}"`
  const lines = [columns.map(cell).join(';'), ...rows.map((r) => columns.map((c) => cell(r[c])).join(';'))]
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv' })) // BOM so Excel reads UTF-8
  a.download = `${name}.csv`
  a.click()
  URL.revokeObjectURL(a.href)
}

type Filters = Record<string, string>

// A row stays if it has the chosen value in every filtered column. `except` leaves one column's filter out
const matches = (row: Row, filters: Filters, except?: string) =>
  Object.entries(filters).every(([c, f]) => c === except || !f || String(row[c] ?? '') === f)

// The values to choose from in a column: those left by the other columns' filters, like in Excel
const choices = (rows: Row[], filters: Filters, column: string) =>
  [...new Set(rows.filter((r) => matches(r, filters, column)).map((r) => String(r[column] ?? '')))]
    .filter((v) => v !== '')
    .sort((a, b) => a.localeCompare(b, 'sv', { numeric: true }))

function Rows({
  table,
  rows,
  shown,
  flagged,
  filters,
  onFilter,
}: {
  table: TemplateTable
  rows: Row[]
  shown: Row[]
  flagged: Set<Row>
  filters: Filters
  onFilter: (column: string, value: string) => void
}) {
  const [sort, setSort] = useState<Sort>(null)
  // A column is numeric if every filled-in value in it is
  const numeric = new Set(
    table.fields
      .filter(
        (f) =>
          rows.some((r) => !isEmpty(r[f.name])) && rows.every((r) => isEmpty(r[f.name]) || isNumber(r[f.name])),
      )
      .map((f) => f.name),
  )
  numeric.add('sida')
  // Long text (descriptions, requirements) wraps at a readable width; short values stay on one line
  const long = new Set(
    table.fields
      .filter((f) => !numeric.has(f.name) && f.type !== 'choice')
      .filter((f) => {
        const lengths = rows.map((r) => String(r[f.name] ?? '').length).filter((n) => n > 0)
        return lengths.length > 0 && lengths.reduce((a, b) => a + b, 0) / lengths.length > 40
      })
      .map((f) => f.name),
  )
  const sorted = sortRows(shown, sort, numeric)
  // Ascending, descending, then back to the documents' own order
  const toggle = (column: string) =>
    setSort(sort?.column !== column ? { column, dir: 1 } : sort.dir === 1 ? { column, dir: -1 } : null)
  const heading = (column: string, text: string, title?: string) => (
    <th
      key={column}
      title={title}
      className={`sortable ${numeric.has(column) ? 'num' : ''} ${sort?.column === column ? 'sorted' : ''}`}
      onClick={() => toggle(column)}
      aria-sort={sort?.column === column ? (sort.dir === 1 ? 'ascending' : 'descending') : undefined}
    >
      {text}
      {sort?.column === column && (sort.dir === 1 ? <ArrowUp /> : <ArrowDown />)}
    </th>
  )
  return (
    <div className="result-table">
      {rows.length > 0 ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                {heading('dokument', 'Dokument')}
                {table.fields.map((f) => heading(f.name, label(f.name), f.description))}
                {heading('sida', 'Sida')}
              </tr>
              <tr className="filters">
                {['dokument', ...table.fields.map((f) => f.name), 'sida'].map((c) => (
                  <th key={c}>
                    <select
                      className={filters[c] ? 'active' : ''}
                      value={filters[c] ?? ''}
                      onChange={(e) => onFilter(c, e.target.value)}
                      aria-label={`Filtrera ${label(c)}`}
                    >
                      <option value="">Alla</option>
                      {choices(rows, filters, c).map((v) => (
                        <option key={v}>{v}</option>
                      ))}
                    </select>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.length === 0 && (
                <tr>
                  <td colSpan={table.fields.length + 2} className="none">
                    Inga rader matchar filtret
                  </td>
                </tr>
              )}
              {sorted.map((row, i) => (
                <tr key={i} className={flagged.has(row) ? 'flagged' : ''}>
                  <td className="doc" title={String(row.dokument ?? '')}>
                    {shortName(String(row.dokument ?? ''))}
                  </td>
                  {table.fields.map((f) => (
                    <td key={f.name} className={numeric.has(f.name) ? 'num' : long.has(f.name) ? 'long' : ''}>
                      <Value field={f} value={row[f.name]} numeric={numeric.has(f.name)} />
                    </td>
                  ))}
                  <td className="num">{row.sida ?? <span className="none">–</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="none">Inget hittat</p>
      )}
    </div>
  )
}

/** One table at a time. "Tabeller" opens a menu like mollie.com: the panel grows down, the page dims
 * and the tables fade up one after the other. The documents' rows in one table, with a filter on every column. */
export function ResultTables({ template, extraction }: { template: Template; extraction: Extraction }) {
  const [active, setActive] = useState(template.tables[0]?.name)
  const [open, setOpen] = useState(false)
  const [filters, setFilters] = useState<Filters>({})
  const closeTimer = useRef<number | undefined>(undefined)
  const documents = extraction.documents.filter((d) => d.status === 'done').map((d) => d.name)

  const table = template.tables.find((t) => t.name === active) ?? template.tables[0]
  if (!table) return null
  const rows = extraction.tables[table.name] ?? []
  const shown = rows.filter((r) => matches(r, filters))
  // Rows a failed check points at (e.g. empty or duplicate values), marked in the table
  const flagged = new Set(
    (extraction.checks ?? [])
      .filter((c) => c.status === 'fail' && c.table === table.name)
      .flatMap((c) => c.rows.map((i) => rows[i])),
  )
  const count = (name: string) => extraction.tables[name]?.length ?? 0

  const show = () => {
    window.clearTimeout(closeTimer.current)
    setOpen(true)
  }
  const hide = () => {
    closeTimer.current = window.setTimeout(() => setOpen(false), 150)
  }
  function pick(name: string) {
    if (name !== active) setFilters({}) // the columns differ between tables
    setActive(name)
    setOpen(false)
  }

  return (
    <>
      <div className={`table-menu ${open ? 'open' : ''}`} onMouseEnter={show} onMouseLeave={hide}>
        <div className="table-menu-bar">
          <button className="table-menu-button" onClick={() => setOpen(!open)}>
            <span className="eyebrow">Tabeller</span>
            <span className="table-menu-current">
              {label(table.name)} <span className="count">{count(table.name)}</span>
            </span>
            <ChevronDown />
          </button>
          <div className="table-menu-tools">
            <button
              disabled={!shown.length}
              onClick={() =>
                downloadCsv(table.name, ['dokument', ...table.fields.map((f) => f.name), 'sida'], shown)
              }
            >
              CSV
            </button>
          </div>
        </div>
        <div className="mega">
          <div className="mega-inner">
            <div className="mega-items">
              {template.tables.map((t, i) => (
                <button
                  key={t.name}
                  className={`mega-item ${t.name === table.name ? 'current' : ''}`}
                  style={{ animationDelay: `${i * 40}ms` }}
                  onClick={() => pick(t.name)}
                >
                  <span className="icon">
                    <Table2 />
                  </span>
                  <span>
                    <span className="mega-title">
                      {label(t.name)} <span className="count">{count(t.name)}</span>
                    </span>
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
      <div className={`backdrop ${open ? 'open' : ''}`} />

      {/* key: a new element per table, so the fade-in runs on every switch */}
      <div key={table.name} className="result-body">
        {documents.length === 0 && <p className="none">Inget dokument gav något resultat. Se felen till vänster.</p>}
        {documents.length > 0 && (
          <Rows
            table={table}
            rows={rows}
            shown={shown}
            flagged={flagged}
            filters={filters}
            onFilter={(c, v) => setFilters({ ...filters, [c]: v })}
          />
        )}
      </div>
    </>
  )
}
