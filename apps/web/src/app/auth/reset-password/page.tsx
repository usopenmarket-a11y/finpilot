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
    <main className="flex min-h-screen items-center justify-center bg-gray-50 dark:bg-gray-950 px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <h1 className="text-3xl font-bold tracking-tight text-gray-900 dark:text-gray-50">
            FinPilot
          </h1>
          <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
            Reset your password
          </p>
        </div>

        <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-6 shadow-sm">
          {status === 'success' ? (
            <div className="space-y-4 text-center">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-green-100 dark:bg-green-900">
                <svg
                  className="h-6 w-6 text-green-600 dark:text-green-400"
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
                <h2 className="text-base font-semibold text-gray-900 dark:text-gray-50">
                  Reset link sent
                </h2>
                <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                  Check your inbox at{' '}
                  <span className="font-medium text-gray-700 dark:text-gray-300">
                    {form.email}
                  </span>{' '}
                  for the password reset link.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setStatus('idle')}
                className="text-sm text-brand-500 hover:text-brand-600 dark:hover:text-brand-400"
              >
                Try a different email
              </button>
            </div>
          ) : (
            <>
              {errors.general && (
                <div
                  role="alert"
                  className="mb-4 rounded-lg bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 px-4 py-3 text-sm text-red-700 dark:text-red-400"
                >
                  {errors.general}
                </div>
              )}

              <form onSubmit={handleSubmit} noValidate className="space-y-4">
                <div className="space-y-1.5">
                  <label
                    htmlFor="email"
                    className="block text-sm font-medium text-gray-700 dark:text-gray-300"
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
                    className="w-full rounded-md border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-50 placeholder-gray-400 dark:placeholder-gray-500 shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 disabled:opacity-50"
                    placeholder="you@example.com"
                    disabled={isLoading}
                  />
                  {errors.email ? (
                    <p id="email-error" className="text-xs text-red-600 dark:text-red-400">
                      {errors.email}
                    </p>
                  ) : (
                    <p id="email-hint" className="text-xs text-gray-400 dark:text-gray-500">
                      We&apos;ll send a password reset link to this address.
                    </p>
                  )}
                </div>

                <button
                  type="submit"
                  disabled={isLoading}
                  className="w-full rounded-md bg-brand-500 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 transition-colors"
                >
                  {isLoading ? 'Sending...' : 'Send Reset Link'}
                </button>
              </form>
            </>
          )}
        </div>

        <p className="text-center text-sm text-gray-500 dark:text-gray-400">
          Remember your password?{' '}
          <Link
            href="/auth/login"
            className="font-medium text-brand-500 hover:text-brand-600 dark:hover:text-brand-400"
          >
            Sign In
          </Link>
        </p>
      </div>
    </main>
  )
}
