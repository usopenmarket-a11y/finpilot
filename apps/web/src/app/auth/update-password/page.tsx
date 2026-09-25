'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { createClient } from '@/lib/supabase/client'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'

export default function UpdatePasswordPage() {
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [ready, setReady] = useState(false)
  const [validSession, setValidSession] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    async function checkSession() {
      try {
        const { data: { user } } = await createClient().auth.getUser()
        if (active) setValidSession(Boolean(user))
      } finally {
        if (active) setReady(true)
      }
    }
    void checkSession().catch(() => {})
    return () => { active = false }
  }, [])

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    if (password.length < 8) { setError('Use at least 8 characters.'); return }
    if (password !== confirmation) { setError('Passwords do not match.'); return }
    setSaving(true)
    try {
      const { error: updateError } = await createClient().auth.updateUser({ password })
      if (updateError) throw updateError
      setPassword('')
      setConfirmation('')
      setSaved(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update your password. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-canvas px-4 py-8">
      <div className="w-full max-w-sm space-y-6">
        <h1 className="text-3xl font-semibold text-ink">Set a new password</h1>
        <div className="rounded-xl border border-line bg-surface p-6 shadow-md">
          {!ready ? <p className="text-sm text-ink-muted" role="status">Checking your reset link…</p>
            : !validSession ? <div className="space-y-3">
              <p className="text-sm text-ink-muted">This reset link is expired or invalid. Request a new link to continue.</p>
              <Link href="/auth/reset-password" className="text-sm text-accent">Request a new reset link</Link>
            </div>
            : saved ? <div className="space-y-3">
              <p role="status" className="text-sm text-positive">Your password has been updated.</p>
              <Link href="/dashboard" className="text-sm text-accent">Continue to dashboard</Link>
            </div>
            : <form onSubmit={handleSubmit} className="space-y-5">
              {error && <p role="alert" className="text-sm text-negative">{error}</p>}
              <Input label="New password" type="password" autoComplete="new-password" minLength={8}
                required value={password} onChange={event => setPassword(event.target.value)} disabled={saving} />
              <Input label="Confirm password" type="password" autoComplete="new-password" minLength={8}
                required value={confirmation} onChange={event => setConfirmation(event.target.value)} disabled={saving} />
              <Button type="submit" disabled={saving} className="w-full">{saving ? 'Saving…' : 'Save password'}</Button>
            </form>}
        </div>
      </div>
    </main>
  )
}
