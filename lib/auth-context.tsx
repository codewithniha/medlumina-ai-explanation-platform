'use client'

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import {
  ApiError,
  getMe,
  login as loginRequest,
  logoutRequest,
  registerDoctor as registerDoctorRequest,
  registerPatient as registerPatientRequest,
  setCsrfToken,
  setUnauthorizedHandler,
  type AuthUser,
  type DoctorInfo,
} from './api-client'

// Who is using the app right now. The SERVER is the source of truth (it checks
// the login cookie on every request); this context only mirrors that answer so
// the screen can show the right thing -- hiding a button is never the security.
type AuthStatus = 'loading' | 'anonymous' | 'authenticated'

type AuthContextValue = {
  status: AuthStatus
  user: AuthUser | null
  doctor: DoctorInfo
  // true when we could not even reach the backend (so "not logged in" is a guess)
  backendUnreachable: boolean
  signIn: (email: string, password: string) => Promise<void>
  signUpPatient: (email: string, password: string, fullName: string) => Promise<void>
  signUpDoctor: (input: {
    email: string
    password: string
    full_name: string
    father_name: string
    pmdc_number: string
  }) => Promise<void>
  signOut: () => Promise<void>
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('loading')
  const [user, setUser] = useState<AuthUser | null>(null)
  const [doctor, setDoctor] = useState<DoctorInfo>(null)
  const [backendUnreachable, setBackendUnreachable] = useState(false)

  const becomeAnonymous = useCallback(() => {
    setCsrfToken(null)
    setUser(null)
    setDoctor(null)
    setStatus('anonymous')
  }, [])

  const refresh = useCallback(async () => {
    try {
      const me = await getMe()
      setBackendUnreachable(false)
      if (me) {
        setUser(me.user)
        setDoctor(me.doctor ?? null)
        setStatus('authenticated')
      } else {
        becomeAnonymous()
      }
    } catch (err) {
      // Could not reach the backend at all (or it errored): show the login
      // screen with an honest message rather than a blank page.
      setBackendUnreachable(!(err instanceof ApiError && err.status))
      becomeAnonymous()
    }
  }, [becomeAnonymous])

  useEffect(() => {
    // Any later 401 (session expired, signed out in another tab) -> login screen.
    setUnauthorizedHandler(becomeAnonymous)
    void refresh()
    return () => setUnauthorizedHandler(null)
  }, [becomeAnonymous, refresh])

  const signIn = useCallback(async (email: string, password: string) => {
    const me = await loginRequest(email, password)
    setBackendUnreachable(false)
    setUser(me.user)
    setStatus('authenticated')
    // /auth/login does not return the doctor profile; ask /auth/me for it.
    void refresh()
  }, [refresh])

  const signUpPatient = useCallback(async (email: string, password: string, fullName: string) => {
    const me = await registerPatientRequest(email, password, fullName)
    setUser(me.user)
    setDoctor(null)
    setStatus('authenticated')
  }, [])

  const signUpDoctor = useCallback(async (input: Parameters<AuthContextValue['signUpDoctor']>[0]) => {
    const me = await registerDoctorRequest(input)
    setUser(me.user)
    setStatus('authenticated')
    void refresh()
  }, [refresh])

  const signOut = useCallback(async () => {
    try {
      await logoutRequest()
    } finally {
      // Full reload: drops every in-memory report, blob URL and session id so
      // nothing from this account can linger on screen for the next person.
      window.location.assign('/')
    }
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      doctor,
      backendUnreachable,
      signIn,
      signUpPatient,
      signUpDoctor,
      signOut,
      refresh,
    }),
    [status, user, doctor, backendUnreachable, signIn, signUpPatient, signUpDoctor, signOut, refresh],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
