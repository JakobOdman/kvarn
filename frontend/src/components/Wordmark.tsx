/** "kvarn" with the r drawn as an old coffee grinder: box with a drawer knob, bowl, crank and handle.
 *  The r is 1 em high with its bottom on the baseline; the handle hangs out over the n. Same art as site/logo/kvarn-r.svg. */
export function Wordmark() {
  return (
    <>
      kva
      <svg className="grinder-r" viewBox="-3 0 31.4 100" overflow="visible" fill="currentColor" aria-label="r">
        <path
          fillRule="evenodd"
          d="M3.5 74H24.5A2 2 0 0 1 26.5 76V98A2 2 0 0 1 24.5 100H3.5A2 2 0 0 1 1.5 98V76A2 2 0 0 1 3.5 74ZM14 85.2A2.8 2.8 0 1 0 14 90.8A2.8 2.8 0 1 0 14 85.2Z"
        />
        <rect x="7.5" y="50" width="13" height="25" />
        <path d="M2 45.4H26L23.5 52H4.5Z" />
        <rect x="12.6" y="35" width="2.8" height="11" />
        <path d="M14 37L33 31" stroke="currentColor" strokeWidth="4.5" strokeLinecap="round" fill="none" />
        <rect x="29.5" y="24" width="8" height="12.5" rx="4" />
      </svg>
      n
    </>
  )
}
