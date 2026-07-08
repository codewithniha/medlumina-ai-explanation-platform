'use client'

import {
  createContext,
  useContext,
  useState,
  useCallback,
  type ReactNode,
} from 'react'

export type ScreenId =
  | 'overview'
  | 'input'
  | 'report'
  | 'visual'
  | 'qa'
  | 'medicine'
  | 'summary'

export type SessionData = {
  reportText: string
  medicines: string[]
  symptoms: string
  hasImage: boolean
  analyzed: boolean
}

const emptySession: SessionData = {
  reportText: '',
  medicines: [],
  symptoms: '',
  hasImage: false,
  analyzed: false,
}

type AppContextValue = {
  screen: ScreenId
  navigate: (screen: ScreenId) => void
  session: SessionData
  setSession: (updater: Partial<SessionData>) => void
  resetSession: () => void
}

const AppContext = createContext<AppContextValue | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const [screen, setScreen] = useState<ScreenId>('overview')
  const [session, setSessionState] = useState<SessionData>(emptySession)

  const navigate = useCallback((next: ScreenId) => {
    setScreen(next)
    if (typeof window !== 'undefined') {
      window.scrollTo({ top: 0, behavior: 'smooth' })
    }
  }, [])

  const setSession = useCallback((updater: Partial<SessionData>) => {
    setSessionState((prev) => ({ ...prev, ...updater }))
  }, [])

  const resetSession = useCallback(() => {
    setSessionState(emptySession)
    setScreen('input')
  }, [])

  return (
    <AppContext.Provider
      value={{ screen, navigate, session, setSession, resetSession }}
    >
      {children}
    </AppContext.Provider>
  )
}

export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used within AppProvider')
  return ctx
}
