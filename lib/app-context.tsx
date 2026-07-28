'use client'

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useMemo,
  type ReactNode,
} from 'react'
import type { AnalysisResult } from './analysis-types'

export type ScreenId =
  | 'landing'
  | 'input'
  | 'report'
  | 'visual'
  | 'qa'
  | 'medicine'
  | 'summary'

// The three ways a patient can use MedLumina.
export type InputMode = 'xray_report' | 'xray_only' | 'prescription_only'

// Which workflow steps exist for each input mode, in order. This powers both
// the sidebar stepper and the progress indicator.
export const modeSteps: Record<InputMode, ScreenId[]> = {
  xray_report: ['input', 'report', 'visual', 'qa', 'medicine', 'summary'],
  xray_only: ['input', 'report', 'visual', 'qa', 'medicine', 'summary'],
  // Prescription-only has no image, so "Visual Explanation" is dropped and the
  // medicine content is folded into step 2 ("Medicine & Condition Insight").
  prescription_only: ['input', 'report', 'qa', 'summary'],
}

export type SessionData = {
  inputMode: InputMode
  reportText: string
  medicines: string[]
  symptoms: string
  hasImage: boolean
  analyzed: boolean
  // Real upload/analysis state (xray_report + xray_only modes only —
  // prescription_only has no backend wired up yet, see input-screen.tsx).
  imagePreviewUrl: string | null
  analysisResult: AnalysisResult | null
  analysisError: string | null
  // Module 4 (RAG Q&A) session state -- separate from analysisResult above,
  // a different backend entirely. sessionId powers the Ask Questions
  // screen; patientCode is the server-generated ID shown to the patient so
  // they can look up this visit again later.
  sessionId: string | null
  patientCode: string | null
}

const emptySession: SessionData = {
  inputMode: 'xray_report',
  reportText: '',
  medicines: [],
  symptoms: '',
  hasImage: false,
  analyzed: false,
  imagePreviewUrl: null,
  analysisResult: null,
  analysisError: null,
  sessionId: null,
  patientCode: null,
}

type AppContextValue = {
  screen: ScreenId
  navigate: (screen: ScreenId) => void
  session: SessionData
  setSession: (updater: Partial<SessionData>) => void
  setInputMode: (mode: InputMode) => void
  resetSession: () => void
  progress: number
  completedSteps: ScreenId[]
  steps: ScreenId[]
  stepEyebrow: (screen: ScreenId) => string
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

  // Switching mode resets only the mode-specific steps — the Upload step stays
  // "visited" so the patient isn't kicked back to a blank slate on a reload.
  const setInputMode = useCallback((mode: InputMode) => {
    setSessionState((prev) => {
      if (prev.inputMode === mode) return prev
      return {
        ...prev,
        inputMode: mode,
        analyzed: false,
        analysisResult: null,
        analysisError: null,
      }
    })
    setVisited((prev) => {
      const next = new Set<ScreenId>()
      if (prev.has('input')) next.add('input')
      return next
    })
  }, [])

  const resetSession = useCallback(() => {
    setSessionState(emptySession)
    setVisited(new Set())
    setScreen('input')
  }, [])

  const steps = useMemo(() => modeSteps[session.inputMode], [session.inputMode])

  const completedSteps = useMemo(
    () => steps.filter((s) => visited.has(s)),
    [steps, visited],
  )

  const progress = useMemo(() => {
    return Math.round((completedSteps.length / steps.length) * 100)
  }, [completedSteps, steps])

  const stepEyebrow = useCallback(
    (target: ScreenId) => {
      const idx = steps.indexOf(target)
      if (idx === -1) return ''
      return `Step ${idx + 1} of ${steps.length}`
    },
    [steps],
  )

  return (
    <AppContext.Provider
      value={{
        screen,
        navigate,
        session,
        setSession,
        setInputMode,
        resetSession,
        progress,
        completedSteps,
        steps,
        stepEyebrow,
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
