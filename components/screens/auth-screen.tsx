'use client'

import { useState, type FormEvent } from 'react'
import { AlertTriangle, Loader2, LogOut, ShieldCheck, Stethoscope, User } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { BrandLogo } from '@/components/brand-logo'
import { useAuth } from '@/lib/auth-context'
import { cn } from '@/lib/utils'

const PASSWORD_MIN = 10

type Mode = 'signin' | 'signup'
type Role = 'patient' | 'doctor'

function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm font-medium text-foreground">{label}</span>
      {children}
      {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
    </label>
  )
}

export function AuthScreen() {
  const { signIn, signUpPatient, signUpDoctor, backendUnreachable } = useAuth()
  const [mode, setMode] = useState<Mode>('signin')
  const [role, setRole] = useState<Role>('patient')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [fatherName, setFatherName] = useState('')
  const [pmdc, setPmdc] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function validate(): string | null {
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) return 'Please enter a valid email address.'
    if (mode === 'signin') return password ? null : 'Please enter your password.'
    if (password.length < PASSWORD_MIN) return `Your password needs at least ${PASSWORD_MIN} characters.`
    if (role === 'doctor') {
      if (!fullName.trim()) return 'Please enter your full name exactly as it appears on the PMDC register.'
      if (!pmdc.trim()) return 'Please enter your PMDC registration number.'
    }
    return null
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    const problem = validate()
    if (problem) {
      setError(problem)
      return
    }
    setBusy(true)
    setError(null)
    try {
      if (mode === 'signin') {
        await signIn(email.trim(), password)
      } else if (role === 'patient') {
        await signUpPatient(email.trim(), password, fullName.trim())
      } else {
        await signUpDoctor({
          email: email.trim(),
          password,
          full_name: fullName.trim(),
          father_name: fatherName.trim(),
          pmdc_number: pmdc.trim(),
        })
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-background px-4 py-10">
      <div className="w-full max-w-md space-y-6">
        <div className="flex justify-center">
          <BrandLogo />
        </div>

        <Card>
          <CardContent className="space-y-5 p-6">
            <div className="grid grid-cols-2 gap-1 rounded-xl bg-muted p-1" role="tablist">
              {(['signin', 'signup'] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  role="tab"
                  aria-selected={mode === m}
                  onClick={() => {
                    setMode(m)
                    setError(null)
                  }}
                  className={cn(
                    'rounded-lg py-2 text-sm font-semibold transition-colors',
                    mode === m ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  {m === 'signin' ? 'Sign in' : 'Create account'}
                </button>
              ))}
            </div>

            {backendUnreachable && (
              <div className="flex gap-2 rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                <span>
                  Can&apos;t reach the MedLumina server. Make sure module4_api.py is running, then reload this page.
                </span>
              </div>
            )}

            {mode === 'signup' && (
              <div className="grid grid-cols-2 gap-2">
                {(
                  [
                    { id: 'patient', label: 'Patient', icon: User },
                    { id: 'doctor', label: 'Doctor', icon: Stethoscope },
                  ] as const
                ).map(({ id, label, icon: Icon }) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => setRole(id)}
                    aria-pressed={role === id}
                    className={cn(
                      'flex items-center justify-center gap-2 rounded-xl border px-3 py-2.5 text-sm font-medium transition-colors',
                      role === id
                        ? 'border-primary bg-primary/10 text-primary'
                        : 'border-border text-muted-foreground hover:text-foreground',
                    )}
                  >
                    <Icon className="size-4" />
                    {label}
                  </button>
                ))}
              </div>
            )}

            <form onSubmit={onSubmit} className="space-y-4" noValidate>
              {mode === 'signup' && (
                <Field
                  label={role === 'doctor' ? 'Full name (as on the PMDC register)' : 'Full name (optional)'}
                >
                  <Input
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    autoComplete="name"
                    maxLength={200}
                  />
                </Field>
              )}

              <Field label="Email">
                <Input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete={mode === 'signin' ? 'username' : 'email'}
                  inputMode="email"
                />
              </Field>

              <Field
                label="Password"
                hint={mode === 'signup' ? `At least ${PASSWORD_MIN} characters. A few random words works well.` : undefined}
              >
                <Input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
                />
              </Field>

              {mode === 'signup' && role === 'doctor' && (
                <>
                  <Field label="Father's name (as on the PMDC register)">
                    <Input
                      value={fatherName}
                      onChange={(e) => setFatherName(e.target.value)}
                      maxLength={200}
                    />
                  </Field>
                  <Field
                    label="PMDC registration number"
                    hint="An administrator checks this against the public PMDC register before your doctor access is switched on."
                  >
                    <Input value={pmdc} onChange={(e) => setPmdc(e.target.value)} maxLength={64} />
                  </Field>
                </>
              )}

              {error && (
                <p role="alert" className="rounded-xl border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  {error}
                </p>
              )}

              <Button type="submit" className="h-11 w-full text-sm" disabled={busy}>
                {busy && <Loader2 className="size-4 animate-spin" />}
                {mode === 'signin' ? 'Sign in' : role === 'doctor' ? 'Register as a doctor' : 'Create patient account'}
              </Button>
            </form>
          </CardContent>
        </Card>

        <p className="flex items-center justify-center gap-1.5 text-center text-xs text-muted-foreground">
          <ShieldCheck className="size-3.5" />
          Your reports and images are visible only to your own account.
        </p>
      </div>
    </div>
  )
}

// Shown to a doctor whose PMDC approval is not active (pending, rejected,
// or expired). They can sign out, but cannot reach anything else.
export function DoctorNotActiveScreen() {
  const { user, doctor, signOut } = useAuth()
  const rejected = user?.status === 'rejected'
  const expired = doctor?.verification_status === 'expired'
  return (
    <div className="flex min-h-dvh items-center justify-center bg-background px-4 py-10">
      <div className="w-full max-w-md space-y-6">
        <div className="flex justify-center">
          <BrandLogo />
        </div>
        <Card>
          <CardContent className="space-y-4 p-6">
            <div className="flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-full bg-primary/15 text-primary">
                <Stethoscope className="size-5" />
              </div>
              <div>
                <p className="font-semibold">
                  {rejected
                    ? 'Doctor access was not approved'
                    : expired
                      ? 'Your PMDC licence date has passed'
                      : 'Waiting for PMDC verification'}
                </p>
                <p className="text-xs text-muted-foreground">
                  {user?.full_name || user?.email}
                  {user?.display_id ? ` · ${user.display_id}` : ''}
                </p>
              </div>
            </div>
            <p className="text-sm leading-relaxed text-muted-foreground">
              {rejected
                ? 'An administrator could not confirm your details against the PMDC register. Please contact the MedLumina team if you think this is a mistake.'
                : expired
                  ? 'Doctor access switches off when the licence date recorded at approval passes. An administrator needs to re-check the PMDC register and renew your approval.'
                  : 'An administrator will check your name and registration number against the public PMDC register. Doctor features unlock as soon as you are approved — you will not need to register again.'}
            </p>
            <Button variant="outline" className="h-10 w-full" onClick={() => void signOut()}>
              <LogOut className="size-4" />
              Sign out
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

// Admin accounts exist only to approve doctors, and that is done with
// approve_doctor.py on the server for now (no admin web screen yet).
export function AdminNoticeScreen() {
  const { user, signOut } = useAuth()
  return (
    <div className="flex min-h-dvh items-center justify-center bg-background px-4 py-10">
      <div className="w-full max-w-md space-y-6">
        <div className="flex justify-center">
          <BrandLogo />
        </div>
        <Card>
          <CardContent className="space-y-4 p-6">
            <p className="font-semibold">
              Administrator account{user?.display_id ? ` · ${user.display_id}` : ''}
            </p>
            <p className="text-sm leading-relaxed text-muted-foreground">
              Administrators approve doctors. For now that is done on the server with{' '}
              <code className="rounded bg-muted px-1 py-0.5 text-xs">python approve_doctor.py</code>; there is no
              admin screen in the web app yet.
            </p>
            <Button variant="outline" className="h-10 w-full" onClick={() => void signOut()}>
              <LogOut className="size-4" />
              Sign out
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
