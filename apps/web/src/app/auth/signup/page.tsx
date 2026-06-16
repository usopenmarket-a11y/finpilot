'use client'

import { useState } from 'react'
import Link from 'next/link'
import { createClient } from '@/lib/supabase/client'

interface FormState {
  fullName: string
  email: string
  password: string
}

interface FormErrors {
  fullName?: string
  email?: string
  password?: string
  general?: string
}

export default function SignupPage() {
  const [form, setForm] = useState<FormState>({
    fullName: '',
    email: '',
    password: '',
  })
  const [errors, setErrors] = useState<FormErrors>({})
  const [isLoading, setIsLoading] = useState(false)
  const [isSuccess, setIsSuccess] = useState(false)

  function validate(): FormErrors {
    const errs: FormErrors = {}
    if (!form.fullName.trim()) errs.fullName = 'Full name is required.'
    if (!form.email) errs.email = 'Email is required.'
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email))
      errs.email = 'Enter a valid email address.'
    if (!form.password) errs.password = 'Password is required.'
    else if (form.password.length < 8)
      errs.password = 'Password must be at least 8 characters.'
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
    setIsLoading(true)

    const supabase = createClient()
    const { error } = await supabase.auth.signUp({
      email: form.email,
      password: form.password,
      options: {
        data: {
          full_name: form.fullName.trim(),
        },
      },
    })

    if (error) {
      setErrors({ general: error.message })
      setIsLoading(false)
      return
    }

    setIsSuccess(true)
    setIsLoading(false)
  }

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const { name, value } = e.target
    setForm((prev) => ({ ...prev, [name]: value }))
    if (errors[name as keyof FormErrors]) {
      setErrors((prev) => ({ ...prev, [name]: undefined }))
    }
  }

  if (isSuccess) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-canvas px-4 py-8">
        <div className="w-full max-w-sm ledger-stagger space-y-4 text-center">
          <div className="rounded-xl border border-positive/30 bg-surface p-6 shadow-md">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-positive-soft">
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
                  d="M5 13l4 4L19 7"
                />
              </svg>
            </div>
            <h2 className="text-xl font-semibold text-ink">
              Check your email
            </h2>
            <p className="mt-2 text-sm text-ink-muted">
              We sent a confirmation link to{' '}
              <span className="font-medium text-ink">
                {form.email}
              </span>
              . Click the link to activate your account.
            </p>
          </div>
          <p className="text-sm text-ink-muted">
            Already confirmed?{' '}
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

  return (
    <main className="flex min-h-screen items-center justify-center bg-canvas px-4 py-8">
      <div className="w-full max-w-sm ledger-stagger">
        {/* Wordmark */}
        <div className="mb-8 text-center">
          <h1 className="text-4xl font-semibold tracking-tight text-ink">
            FinPilot
          </h1>
          <p className="mt-2 text-sm text-ink-muted">
            Create your account
          </p>
        </div>

        {/* Card */}
        <div className="rounded-xl border border-line bg-surface p-6 shadow-md">
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
                htmlFor="fullName"
                className="block text-sm font-medium text-ink"
              >
                Full name
              </label>
              <input
                id="fullName"
                name="fullName"
                type="text"
                autoComplete="name"
                value={form.fullName}
                onChange={handleChange}
                aria-describedby={errors.fullName ? 'fullName-error' : undefined}
                aria-invalid={!!errors.fullName}
                className="w-full rounded-lg border border-line-strong bg-surface-sunken px-3 py-2.5 text-sm text-ink placeholder-ink-faint shadow-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-50 transition-colors"
                placeholder="Ahmed Mohamed"
                disabled={isLoading}
              />
              {errors.fullName && (
                <p id="fullName-error" className="text-xs text-negative">
                  {errors.fullName}
                </p>
              )}
            </div>

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
                aria-describedby={errors.email ? 'email-error' : undefined}
                aria-invalid={!!errors.email}
                className="w-full rounded-lg border border-line-strong bg-surface-sunken px-3 py-2.5 text-sm text-ink placeholder-ink-faint shadow-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-50 transition-colors"
                placeholder="you@example.com"
                disabled={isLoading}
              />
              {errors.email && (
                <p id="email-error" className="text-xs text-negative">
                  {errors.email}
                </p>
              )}
            </div>

            <div className="space-y-1.5">
              <label
                htmlFor="password"
                className="block text-sm font-medium text-ink"
              >
                Password
              </label>
              <input
                id="password"
                name="password"
                type="password"
                autoComplete="new-password"
                value={form.password}
                onChange={handleChange}
                aria-describedby={errors.password ? 'password-error' : 'password-hint'}
                aria-invalid={!!errors.password}
                className="w-full rounded-lg border border-line-strong bg-surface-sunken px-3 py-2.5 text-sm text-ink placeholder-ink-faint shadow-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-50 transition-colors"
                placeholder="••••••••"
                disabled={isLoading}
              />
              {errors.password ? (
                <p id="password-error" className="text-xs text-negative">
                  {errors.password}
                </p>
              ) : (
                <p id="password-hint" className="text-xs text-ink-faint">
                  Minimum 8 characters.
                </p>
              )}
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="w-full rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-accent-hover focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 transition-colors"
            >
              {isLoading ? 'Creating account…' : 'Sign Up'}
            </button>
          </form>
        </div>

        <p className="mt-6 text-center text-sm text-ink-muted">
          Already have an account?{' '}
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
