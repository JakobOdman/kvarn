import { useState } from 'react'
import { login, type User } from '../api'
import { Wordmark } from './Wordmark'

/** E-mail and password, checked by Supabase. Accounts are made by hand for now (Supabase: Authentication -> Users). */
export function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onLogin(await login(email, password))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <form className="card login-card" onSubmit={submit}>
        <span className="wordmark login-wordmark" aria-label="kvarn">
          <Wordmark />
        </span>
        <p className="login-lead">Logga in för att läsa och mala dina dokument.</p>
        <label>
          <span className="caps">E-post</span>
          <input
            type="email"
            autoComplete="username"
            autoFocus
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label>
          <span className="caps">Lösenord</span>
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && <p className="read-warning">{error}</p>}
        <button className="primary" disabled={busy || !email || !password}>
          {busy ? 'Loggar in…' : 'Logga in'}
        </button>
        <p className="login-note">
          Inget konto? <a href="mailto:hej@thekvarn.com?subject=Tillg%C3%A5ng%20till%20Kvarn">Be om tillgång</a>
        </p>
        <a className="login-back" href="/">
          ← Till startsidan
        </a>
      </form>
    </div>
  )
}
