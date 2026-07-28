import type { AnalysisResult, AnalyzeParams } from './analysis-types'

// Calls our own Next.js route (app/api/analyze/route.ts), which in turn
// proxies to the Kaggle backend (server.py) over its ngrok URL. We go
// through our own API route rather than calling the ngrok URL directly
// from the browser so the backend URL never has to be exposed client-side
// and so CORS is a non-issue.
export async function runAnalysis(params: AnalyzeParams): Promise<AnalysisResult> {
  const formData = new FormData()
  formData.append('image', params.image)
  if (params.reportText) formData.append('report_text', params.reportText)
  if (params.probThreshold != null) formData.append('prob_threshold', String(params.probThreshold))
  if (params.regionThreshold != null) formData.append('region_threshold', String(params.regionThreshold))
  if (params.maxDiseasesToShow != null) formData.append('max_diseases_to_show', String(params.maxDiseasesToShow))

  const res = await fetch('/api/analyze', {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    let message = `Analysis failed (${res.status})`
    try {
      const body = await res.json()
      if (body?.error) message = body.error
    } catch {
      // response wasn't JSON — keep the generic message
    }
    throw new Error(message)
  }

  return (await res.json()) as AnalysisResult
}

// ── Module 4 (RAG Q&A backend) — separate FastAPI server, not the Kaggle
// image-analysis backend above. Called directly from the browser (not
// through a Next.js API route like runAnalysis), since it doesn't need
// the image and CORS is already enabled on that server for this reason.
const MODULE4_API_BASE_URL =
  process.env.NEXT_PUBLIC_MODULE4_API_BASE_URL || 'http://127.0.0.1:8001'

export type StartSessionPayload = {
  doctor_report: string
  xray_findings: Record<string, string>
  prescribed_medicines: string[]
  symptoms?: string
  explanation_level?: 'simple' | 'detailed'
  patient_code?: string
  patient_name?: string
}

export type StartSessionResult = {
  session_id: string
  chunks_indexed: number
  explanation_level: string
  patient_id: string | null
  patient_code: string | null
}

export type AskQuestionResult = {
  classification: 'SESSION_GROUNDED' | 'GENERAL_MEDICAL' | 'OFF_TOPIC' | null
  answer: string
  confidence: number | null
}

export type PatientSessionSummary = {
  session_id: string
  created_at: string
  explanation_level: string
}

export type PatientLookupResult = {
  patient_id: string
  sessions: PatientSessionSummary[]
}

export type TurnOut = {
  question: string
  classification: 'SESSION_GROUNDED' | 'GENERAL_MEDICAL' | 'OFF_TOPIC' | null
  answer: string
  confidence: number | null
}

export type SessionHistoryResult = {
  turns: TurnOut[]
}

export class ApiError extends Error {
  constructor(message: string, public status?: number) {
    super(message)
    this.name = 'ApiError'
  }
}

async function module4PostJson<T>(path: string, body: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${MODULE4_API_BASE_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    throw new ApiError(
      `Could not reach the Module 4 backend at ${MODULE4_API_BASE_URL}. Is module4_api.py running?`,
    )
  }

  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new ApiError(`Backend returned ${res.status}: ${detail}`, res.status)
  }

  return res.json() as Promise<T>
}

export function startSession(
  payload: StartSessionPayload,
): Promise<StartSessionResult> {
  return module4PostJson<StartSessionResult>('/session/start', payload)
}

export function askQuestion(
  session_id: string,
  question: string,
): Promise<AskQuestionResult> {
  return module4PostJson<AskQuestionResult>('/session/ask', { session_id, question })
}

export function lookupPatient(
  patient_code: string,
): Promise<PatientLookupResult> {
  return module4PostJson<PatientLookupResult>('/patient/lookup', { patient_code })
}

export function getSessionHistory(
  session_id: string,
): Promise<SessionHistoryResult> {
  return module4PostJson<SessionHistoryResult>('/session/history', { session_id })
}

export type HealthResult = {
  status: string
  medgemma_configured: boolean
  medgemma_reachable: boolean
}

// Real check, not a display fake -- see module4_api.py's /health for why
// this exists (confirmed live: MedGemma being down while the UI still
// showed "Online"). Deliberately doesn't throw on failure -- an
// unreachable backend IS the answer this function needs to report, not
// an error state the caller has to handle separately.
export async function checkHealth(): Promise<HealthResult> {
  try {
    const res = await fetch(`${MODULE4_API_BASE_URL}/health`, {
      signal: AbortSignal.timeout(4000),
    })
    if (!res.ok) throw new Error('unhealthy')
    return (await res.json()) as HealthResult
  } catch {
    return { status: 'unreachable', medgemma_configured: false, medgemma_reachable: false }
  }
}

export type TranscribeReportResult = {
  extracted_text: string
  found_text: boolean
}

// Sends a photo of a doctor's handwritten report for transcription. Uses
// FormData (multipart upload), not JSON -- this is a real file, not text.
// Matches the limit enforced server-side in module4_api.py's
// /report/transcribe endpoint -- checked here too so a patient gets an
// instant, clear rejection instead of waiting through an upload just to
// have the server reject it after the fact.
const MAX_REPORT_FILE_BYTES = 20 * 1024 * 1024 // 20MB

export async function transcribeReport(image: File): Promise<TranscribeReportResult> {
  if (image.size > MAX_REPORT_FILE_BYTES) {
    throw new ApiError(
      `This file is ${(image.size / (1024 * 1024)).toFixed(1)}MB, which is over the 20MB limit. Please use a smaller photo or a compressed PDF.`,
    )
  }

  const formData = new FormData()
  formData.append('image', image)

  let res: Response
  try {
    res = await fetch(`${MODULE4_API_BASE_URL}/report/transcribe`, {
      method: 'POST',
      body: formData,
    })
  } catch {
    throw new ApiError(
      `Could not reach the Module 4 backend at ${MODULE4_API_BASE_URL}. Is module4_api.py running?`,
    )
  }

  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new ApiError(`Backend returned ${res.status}: ${detail}`, res.status)
  }

  return res.json() as Promise<TranscribeReportResult>
}
