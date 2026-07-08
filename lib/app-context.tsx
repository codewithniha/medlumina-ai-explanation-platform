'use client'

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useMemo,
  type ReactNode,
} from 'react'

export type ScreenId =
  | 'landing'
  | 'input'
  | 'report'
  | 'visual'
  | 'qa'
  | 'medicine'
  | 'summary'

// The ordered patient workflow, used to power the sidebar progress indicator.
export const workflowSteps: ScreenId[] = [
  'input',
  'report',
  'visual',
  'qa',
  'medicine',
  'summary',
]

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
  progress: number
  completedSteps: ScreenId[]
}

const AppContext = createContext<AppContextValue | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const [screen, setScreen] = useState<ScreenId>('landing')
  const [session, setSessionState] = useState<SessionData>(emptySession)
  const [visited, setVisited] = useState<Set<ScreenId>>(new Set())

  const navigate = useCallback((next: ScreenId) => {
    setScreen(next)
    setVisited((prev) => {
      if (prev.has(next)) return prev
      const updated = new Set(prev)
      updated.add(next)
      return updated
    })
    if (typeof window !== 'undefined') {
      window.scrollTo({ top: 0, behavior: 'smooth' })
    }
  }, [])

  const setSession = useCallback((updater: Partial<SessionData>) => {
    setSessionState((prev) => ({ ...prev, ...updater }))
  }, [])

  const resetSession = useCallback(() => {
    setSessionState(emptySession)
    setVisited(new Set())
    setScreen('input')
  }, [])

  const completedSteps = useMemo(
    () => workflowSteps.filter((s) => visited.has(s)),
    [visited],
  )

  const progress = useMemo(() => {
    return Math.round((completedSteps.length / workflowSteps.length) * 100)
  }, [completedSteps])

  return (
    <AppContext.Provider
      value={{
        screen,
        navigate,
        session,
        setSession,
        resetSession,
        progress,
        completedSteps,
      }}
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
