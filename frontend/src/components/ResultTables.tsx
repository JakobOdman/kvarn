import { ChevronDown, Table2 } from 'lucide-react'
import { useRef, useState } from 'react'
import type { Extraction, Template, TemplateField, TemplateTable } from '../api'

type Row = Extraction['tables'][string][number]

const label = (name: string) => name.charAt(0).toUpperCase() + name.slice(1).replace(/_/g, ' ')

// "22,401,237", "(300)", "10.8%" - right-aligned with even digits
// A dash in an amount column means the value is missing, not that the column is text
const isEmpty = (v: unknown) => v === null || v === '' || (typeof v === 'string' && /^[-–]$/.test(v.trim()))

const isNumber = (v: unknown) =>
  typeof v === 'number' || (typeof v === 'string' && /^[(\-–−]?[\d\s.,]+%?\)?$/.test(v.trim()) && /\d/.test(v))

function Value({ field, value }: { field: TemplateField; value: Row[string] }) {
  if (value === null || value === '') return <span className="none">–</span>
  if (field.type === 'choice') return <span className="badge">{value}</span>
  return <>{value}</>
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
  // A column is numeric if every filled-in value in it is
  const numeric = new Set(
    table.fields
      .filter(
        (f) =>
          rows.some((r) => !isEmpty(r[f.name])) && rows.every((r) => isEmpty(r[f.name]) || isNumber(r[f.name])),
      )
      .map((f) => f.name),
  )
  return (
    <div className="result-table">
      {rows.length > 0 ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Dokument</th>
                {table.fields.map((f) => (
                  <th key={f.name} title={f.description} className={numeric.has(f.name) ? 'num' : ''}>
                    {label(f.name)}
                  </th>
                ))}
                <th className="num">Sida</th>
              </tr>
              <tr className="filters">
                {['dokument', ...table.fields.map((f) => f.name), 'sida'].map((c) => (
                  <th key={c}>
                    <select
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
              {shown.map((row, i) => (
                <tr key={i} className={flagged.has(row) ? 'flagged' : ''}>
                  <td>{row.dokument}</td>
                  {table.fields.map((f) => (
                    <td key={f.name} className={numeric.has(f.name) ? 'num' : ''}>
                      <Value field={f} value={row[f.name]} />
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
