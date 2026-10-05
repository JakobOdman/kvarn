import type { ReactNode } from 'react'

/** A labelled switch: name and a short explanation on the left, the switch on the right. */
export function Toggle({
  label,
  description,
  badge,
  checked,
  onChange,
}: {
  label: string
  description: string
  badge?: ReactNode // shown next to the name while on, e.g. "Kostar"
  checked: boolean
  onChange: (checked: boolean) => void
}) {
  return (
    <label className={`toggle ${checked ? 'on' : ''}`}>
      <span className="toggle-text">
        <span className="toggle-label">
          {label}
          {checked && badge}
        </span>
        <span className="toggle-description">{description}</span>
      </span>
      <input type="checkbox" role="switch" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="switch" aria-hidden />
    </label>
  )
}
