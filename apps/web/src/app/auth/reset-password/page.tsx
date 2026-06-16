'use client'

import { useState } from 'react'
import Link from 'next/link'
import { createClient } from '@/lib/supabase/client'

interface FormState {
  email: string
}

interface FormErrors {
  email?: string
  general?: string
}

type PageStatus = 'idle' | 'loading' | 'success' | 'error'

export default function ResetPasswordPage() {
  const [form, setForm] = useState<FormState>({ email: '' })
  const [errors, setErrors] = useState<FormErrors>({})
  const [status, setStatus] = useState<PageStatus>('idle')

  function validate(): FormErrors {
    const errs: FormErrors = {}
    if (!form.email) errs.email = 'Email is required.'
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email))
      errs.email = 'Enter a valid email address.'
    return errs
  }

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const errs = validate()
    if (Object.keys(errs).length > 0) {
      setErrors(errs)
      return
    }

    setErrors({})
    setStatus('loading')

    const supabase = createClient()
    const { error } = await supabase.auth.resetPasswordForEmail(form.email, {
      redirectTo: `${window.location.origin}/auth/callback`,
    })

    if (error) {
      setErrors({ general: error.message })
      setStatus('error')
      return
    }

    setStatus('success')
  }

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    setForm({ email: e.target.value })
    if (errors.email) setErrors({})
  }

  const isLoading = status === 'loading'

  return (
    <main className="flex min-h-screen items-center justify-center bg-canvas px-4 py-8">
      <div className="w-full max-w-sm ledger-stagger">
        {/* Wordmark */}
        <div className="mb-8 text-center">
          <h1 className="text-4xl font-semibold tracking-tight text-ink">
            FinPilot
          </h1>
          <p className="mt-2 text-sm text-ink-muted">
            Reset your password
          </p>
        </div>

        {/* Card */}
        <div className="rounded-xl border border-line bg-surface p-6 shadow-md">
          {status === 'success' ? (
            <div className="space-y-4 text-center">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-positive-soft">
                <svg
                  className="h-6 w-6 text-positive"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
                  />
                </svg>
              </div>
              <div>
                <h2 className="text-base font-semibold text-ink">
                  Reset link sent
                </h2>
                <p className="mt-1 text-sm text-ink-muted">
                  Check your inbox at{' '}
                  <span className="font-medium text-ink">
                    {form.email}
                  </span>{' '}
                  for the password reset link.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setStatus('idle')}
                className="text-sm text-accent hover:text-accent-hover transition-colors"
              >
                Try a different email
              </button>
            </div>
          ) : (
            <>
              {errors.general && (
                <div
                  role="alert"
                  className="mb-5 rounded-lg bg-negative-soft border border-negative/20 px-4 py-3 text-sm text-negative"
                >
                  {errors.general}
                </div>
              )}

              <form onSubmit={handleSubmit} noValidate className="space-y-5">
                <div className="space-y-1.5">
                  <label
                    htmlFor="email"
                    className="block text-sm font-medium text-ink"
                  >
                    Email
                  </label>
                  <input
                    id="email"
                    name="email"
                    type="email"
                    autoComplete="email"
                    value={form.email}
                    onChange={handleChange}
                    aria-describedby={errors.email ? 'email-error' : 'email-hint'}
                    aria-invalid={!!errors.email}
                    className="w-full rounded-lg border border-line-strong bg-surface-sunken px-3 py-2.5 text-sm text-ink placeholder-ink-faint shadow-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-50 transition-colors"
                    placeholder="you@example.com"
                    disabled={isLoading}
                  />
                  {errors.email ? (
                    <p id="email-error" className="text-xs text-negative">
                      {errors.email}
                    </p>
                  ) : (
                    <p id="email-hint" className="text-xs text-ink-faint">
                      We&apos;ll send a password reset link to this address.
                    </p>
                  )}
                </div>

                <button
                  type="submit"
                  disabled={isLoading}
                  className="w-full rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-accent-hover focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 transition-colors"
                >
                  {isLoading ? 'Sending…' : 'Send Reset Link'}
                </button>
              </form>
            </>
          )}
        </div>

        <p className="mt-6 text-center text-sm text-ink-muted">
          Remember your password?{' '}
          <Link
            href="/auth/login"
            className="font-medium text-accent hover:text-accent-hover transition-colors"
          >
            Sign In
          </Link>
        </p>
      </div>
    </main>
  )
}
