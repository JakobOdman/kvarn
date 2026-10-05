import type { Rule, TemplateTable } from '../api'

const TYPES: Record<Rule['type'], string> = {
  sum: 'Summa',
  count: 'Antal rader',
  required: 'Ifyllt',
  unique: 'Unikt',
}

export const newRule = (tables: TemplateTable[]): Rule => ({
  type: 'sum',
  table: tables[0]?.name ?? '',
  field: tables[0]?.fields[0]?.name ?? '',
  target_table: '',
  target_field: '',
})

/** One check: type, then table and field from the template, and for sum and count what to compare with. */
export function RuleEditor({
  rule,
  tables,
  onChange,
  onRemove,
}: {
  rule: Rule
  tables: TemplateTable[]
  onChange: (rule: Rule) => void
  onRemove: () => void
}) {
  const fieldsOf = (table: string) => tables.find((t) => t.name === table)?.fields ?? []
  const set = (changes: Partial<Rule>) => onChange({ ...rule, ...changes })
  const compares = rule.type === 'sum' || rule.type === 'count'

  const tableSelect = (value: string, change: (table: string) => void) => (
    <select value={value} onChange={(e) => change(e.target.value)}>
      <option value="">Tabell…</option>
      {tables.map((t) => (
        <option key={t.name} value={t.name}>
          {t.name}
        </option>
      ))}
    </select>
  )
  const fieldSelect = (table: string, value: string, change: (field: string) => void) => (
    <select value={value} onChange={(e) => change(e.target.value)}>
      <option value="">Fält…</option>
      {fieldsOf(table).map((f) => (
        <option key={f.name} value={f.name}>
          {f.name}
        </option>
      ))}
    </select>
  )

  return (
    <div className="rule">
      <select value={rule.type} onChange={(e) => set({ type: e.target.value as Rule['type'] })}>
        {Object.entries(TYPES).map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>
      <span className="rule-word">{rule.type === 'count' ? 'i' : 'av'}</span>
      {tableSelect(rule.table, (table) => set({ table, field: fieldsOf(table)[0]?.name ?? '' }))}
      {rule.type !== 'count' && fieldSelect(rule.table, rule.field, (field) => set({ field }))}
      {compares && (
        <>
          <span className="rule-word">=</span>
          {tableSelect(rule.target_table, (target_table) =>
            set({ target_table, target_field: fieldsOf(target_table)[0]?.name ?? '' }),
          )}
          {fieldSelect(rule.target_table, rule.target_field, (target_field) => set({ target_field }))}
        </>
      )}
      <button onClick={onRemove} title="Ta bort kontrollen">
        ✕
      </button>
    </div>
  )
}
