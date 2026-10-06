import { ChevronRight, LayoutTemplate, Lock } from 'lucide-react'
import { newRule, RuleEditor } from './RuleEditor'
import { useEffect, useState } from 'react'
import {
  deleteTemplate,
  listTemplates,
  lockTemplate,
  MODELS,
  saveTemplate,
  type Model,
  type Template,
  type TemplateField,
  type TemplateTable,
} from '../api'

const SECTIONS = { instruction: 'Instruktion', tables: 'Tabeller', rules: 'Kontroller' }
type Section = keyof typeof SECTIONS

const newField = (): TemplateField => ({ name: '', description: '', type: 'text', choices: [] })
const newTable = (): TemplateTable => ({ name: '', description: '', fields: [newField()] })
const newTemplate = (): Template => ({
  id: '',
  name: '',
  prompt: '',
  tables: [newTable()],
  model: 'gpt-5.4-mini',
  page_selection: false,
  rules: [],
  locked: false,
})

/** List of templates on the left, the selected one as a form on the right. */
export function TemplateEditor() {
  const [templates, setTemplates] = useState<Template[]>([])
  const [draft, setDraft] = useState<Template | null>(null)
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null)
  const [expanded, setExpanded] = useState<Set<number>>(new Set()) // table indexes shown open
  const [section, setSection] = useState<Section>('instruction')

  useEffect(() => {
    listTemplates().then(setTemplates)
  }, [])

  function open(template: Template) {
    setDraft(structuredClone(template))
    setMessage(null)
    setExpanded(new Set(template.id ? [] : [0])) // a new template starts with its table open
    setSection('instruction')
  }

  function toggle(ti: number) {
    setExpanded((s) => {
      const next = new Set(s)
      if (next.has(ti)) next.delete(ti)
      else next.add(ti)
      return next
    })
  }

  function addTable() {
    setDraft((d) => d && { ...d, tables: [...d.tables, newTable()] })
    setExpanded((s) => new Set([...s, draft!.tables.length]))
  }

  function removeTable(ti: number) {
    setDraft((d) => d && { ...d, tables: d.tables.filter((_, j) => j !== ti) })
    setExpanded((s) => new Set([...s].filter((i) => i !== ti).map((i) => (i > ti ? i - 1 : i))))
  }

  /** Save, and with lock also lock it: unsaved changes are kept either way. */
  async function save(lock = false) {
    if (!draft) return
    const clean = {
      ...draft,
      locked: lock,
      tables: draft.tables.map((t) => ({
        ...t,
        fields: t.fields.map((f) => ({ ...f, choices: f.type === 'choice' ? f.choices.filter(Boolean) : [] })),
      })),
    }
    try {
      const saved = await saveTemplate(clean)
      setDraft(saved)
      setTemplates(await listTemplates())
      setMessage({ text: lock ? 'Sparad och låst.' : 'Sparad.', error: false })
    } catch (e) {
      setMessage({ text: (e as Error).message, error: true })
    }
  }

  async function unlock() {
    const saved = await lockTemplate(draft!.id, false)
    setDraft(saved)
    setTemplates(await listTemplates())
    setMessage(null)
  }

  async function remove() {
    if (!draft?.id || !confirm(`Ta bort mallen ${draft.name}?`)) return
    await deleteTemplate(draft.id)
    setDraft(null)
    setTemplates(await listTemplates())
  }

  const updateTable = (i: number, changes: Partial<TemplateTable>) =>
    setDraft((d) => d && { ...d, tables: d.tables.map((t, j) => (j === i ? { ...t, ...changes } : t)) })

  const updateField = (ti: number, fi: number, changes: Partial<TemplateField>) =>
    updateTable(ti, { fields: draft!.tables[ti].fields.map((f, j) => (j === fi ? { ...f, ...changes } : f)) })

  return (
    <>
      <section className="card">
        <span className="caps">Mallar</span>
        <ul className="queue">
          {templates.map((t) => (
            <li key={t.id} className={`done ${t.id === draft?.id ? 'selected' : ''}`} onClick={() => open(t)}>
              <span className="icon">
                <LayoutTemplate />
              </span>
              <div>
                <div className="queue-name">
                  {t.name}
                  {t.locked && <Lock className="locked-icon" aria-label="Låst" />}
                </div>
                <div className="queue-meta">{t.tables.map((tb) => tb.name).join(', ')}</div>
              </div>
            </li>
          ))}
        </ul>
        <button className="new-template" onClick={() => open(newTemplate())}>
          Ny mall
        </button>
      </section>

      {!draft ? (
        <div className="empty">Välj eller skapa en mall</div>
      ) : (
        <div className="card template-form">
          <nav className="nav form-tabs">
            {(Object.keys(SECTIONS) as Section[]).map((key) => (
              <button key={key} className={key === section ? 'active' : ''} onClick={() => setSection(key)}>
                {SECTIONS[key]}
                {key === 'tables' && <span className="count">{draft.tables.length}</span>}
                {key === 'rules' && <span className="count">{(draft.rules ?? []).length}</span>}
              </button>
            ))}
          </nav>

          {draft.locked && <p className="locked-note">Mallen är låst. Lås upp den för att ändra den.</p>}
          {/* A locked template can be read but not changed */}
          <fieldset className="template-fields" disabled={draft.locked}>
            {section === 'instruction' && (
              <div key="instruction" className="form-section">
                <label>
                  <span className="caps">Namn</span>
                  <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
                </label>
                <label>
                  <span className="caps">Modell</span>
                  <select value={draft.model} onChange={(e) => setDraft({ ...draft, model: e.target.value as Model })}>
                    {(Object.keys(MODELS) as Model[]).map((m) => (
                      <option key={m} value={m}>
                        {MODELS[m]}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span className="caps">Prompt</span>
                  <textarea
                    rows={12}
                    value={draft.prompt}
                    placeholder="Vad ska AI:n plocka ut, och vilka regler gäller?"
                    onChange={(e) => setDraft({ ...draft, prompt: e.target.value })}
                  />
                </label>
              </div>
            )}

            {section === 'tables' && (
              <div key="tables" className="form-section">
                {draft.tables.map((table, ti) => {
                  const isOpen = expanded.has(ti)
                  return (
                    <div key={ti} className={`template-table ${isOpen ? 'open' : ''}`}>
                      <div className="template-table-head" onClick={() => toggle(ti)}>
                        <ChevronRight />
                        <span className="caps">Tabell {ti + 1}</span>
                        <span className="template-table-name">{table.name || 'Namnlös'}</span>
                        <span className="queue-meta">{table.fields.length} fält</span>
                        <span className="spacer" />
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            removeTable(ti)
                          }}
                          title="Ta bort tabellen"
                        >
                          ✕
                        </button>
                      </div>

                      <div className="collapse">
                        <div className="collapse-inner">
                          <div className="template-table-body">
                            <div className="row">
                              <input
                                placeholder="Namn"
                                value={table.name}
                                onChange={(e) => updateTable(ti, { name: e.target.value })}
                              />
                              <input
                                placeholder="Beskrivning, t.ex. en rad per bolag"
                                value={table.description}
                                onChange={(e) => updateTable(ti, { description: e.target.value })}
                              />
                            </div>

                            {table.fields.map((field, fi) => (
                              <div key={fi} className="row field">
                                <input
                                  placeholder="Fält"
                                  value={field.name}
                                  onChange={(e) => updateField(ti, fi, { name: e.target.value })}
                                />
                                <input
                                  placeholder="Beskrivning"
                                  value={field.description}
                                  onChange={(e) => updateField(ti, fi, { description: e.target.value })}
                                />
                                <select
                                  value={field.type}
                                  onChange={(e) => updateField(ti, fi, { type: e.target.value as TemplateField['type'] })}
                                >
                                  <option value="text">Text</option>
                                  <option value="integer">Heltal</option>
                                  <option value="choice">Val</option>
                                </select>
                                {field.type === 'choice' && (
                                  <input
                                    placeholder="Värden, kommaseparerade"
                                    value={field.choices.join(', ')}
                                    onChange={(e) =>
                                      updateField(ti, fi, { choices: e.target.value.split(',').map((c) => c.trim()) })
                                    }
                                  />
                                )}
                                <button
                                  onClick={() => updateTable(ti, { fields: table.fields.filter((_, j) => j !== fi) })}
                                  title="Ta bort fältet"
                                >
                                  ✕
                                </button>
                              </div>
                            ))}
                            <button
                              className="add-field"
                              onClick={() => updateTable(ti, { fields: [...table.fields, newField()] })}
                            >
                              Lägg till fält
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  )
                })}

                <p className="engine-note">
                  Varje rad får också <code>dokument</code> och <code>sida</code> automatiskt.
                </p>
                <button className="add-field" onClick={addTable}>
                  Lägg till tabell
                </button>
              </div>
            )}

            {section === 'rules' && (
              <div key="rules" className="form-section">
                <div className="rules">
                  <p className="engine-note">
                    Räknas efter extraktionen, per dokument. Gratis. Summa jämför med 0,5 % tolerans.
                  </p>
                  {(draft.rules ?? []).map((rule, i) => (
                    <RuleEditor
                      key={i}
                      rule={rule}
                      tables={draft.tables}
                      onChange={(r) => setDraft({ ...draft, rules: draft.rules.map((x, j) => (j === i ? r : x)) })}
                      onRemove={() => setDraft({ ...draft, rules: draft.rules.filter((_, j) => j !== i) })}
                    />
                  ))}
                  <button
                    className="add-field"
                    onClick={() => setDraft({ ...draft, rules: [...(draft.rules ?? []), newRule(draft.tables)] })}
                  >
                    Lägg till kontroll
                  </button>
                </div>
              </div>
            )}
          </fieldset>

          <div className="row actions">
            <span className="spacer" />
            {draft.locked ? (
              <button onClick={unlock}>Lås upp</button>
            ) : (
              <>
                {draft.id && <button onClick={remove}>Ta bort mall</button>}
                <button onClick={() => save(true)}>Spara och lås</button>
                <button className="primary" onClick={() => save()}>
                  Spara
                </button>
              </>
            )}
          </div>
          {message && <p className={message.error ? 'read-warning' : 'saved'}>{message.text}</p>}
        </div>
      )}
    </>
  )
}
