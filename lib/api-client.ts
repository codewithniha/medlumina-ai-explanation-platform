import type { AnalysisResult, AnalyzeParams, QualifiedNotShown } from './analysis-types'

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
//
// STEP 4b-1 (accounts): Module 4 now requires a login. The login is a cookie
// (ml_session, HttpOnly) that the browser attaches by itself as long as every
// request says credentials: 'include'. Every request that CHANGES something
// (POST) must also carry the X-CSRF-Token header the server gave us at login.
// Both are handled in ONE place below (module4Fetch), so no screen has to
// remember them.
//
// Use "localhost", not "127.0.0.1": the page lives on localhost:3000, and the
// browser only treats localhost:8001 as the same site (so it sends the login
// cookie). resolveBaseUrl() fixes an old 127.0.0.1 setting automatically.
const CONFIGURED_MODULE4_URL =
  process.env.NEXT_PUBLIC_MODULE4_API_BASE_URL || 'http://localhost:8001'

function resolveBaseUrl(): string {
  let url = CONFIGURED_MODULE4_URL
  if (typeof window !== 'undefined') {
    try {
      const u = new URL(url)
      if (u.hostname === '127.0.0.1' && window.location.hostname === 'localhost') {
        u.hostname = 'localhost'
        url = u.toString()
      }
    } catch {
      // not a valid URL -- leave it alone, fetch will report the problem
    }
  }
  return url.replace(/\/$/, '')
}

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
  classification: 'SESSION_GROUNDED' | 'TREND_COMPARISON' | 'GENERAL_MEDICAL' | 'OFF_TOPIC' | null
  answer: string
  confidence: number | null
  insufficient_session_data: boolean
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
  classification: 'SESSION_GROUNDED' | 'TREND_COMPARISON' | 'GENERAL_MEDICAL' | 'OFF_TOPIC' | null
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

// ── Login state shared by every request ──────────────────────────────────────
let csrfToken: string | null = null
let unauthorizedHandler: (() => void) | null = null

export function setCsrfToken(token: string | null) {
  csrfToken = token
}

// Called when ANY request comes back 401 ("you are not logged in any more",
// e.g. the session expired). The auth context uses it to show the login screen.
export function setUnauthorizedHandler(handler: (() => void) | null) {
  unauthorizedHandler = handler
}

type FetchOptions = {
  method?: 'GET' | 'POST'
  json?: unknown
  form?: FormData
  // The login/me calls EXPECT a 401 sometimes; they must not trigger the
  // "session expired" handler.
  expectUnauthorized?: boolean
}

async function module4Fetch(path: string, options: FetchOptions = {}): Promise<Response> {
  const base = resolveBaseUrl()
  const method = options.method ?? (options.json !== undefined || options.form ? 'POST' : 'GET')
  const headers: Record<string, string> = {}
  let body: BodyInit | undefined
  if (options.json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.json)
  } else if (options.form) {
    body = options.form // the browser sets the multipart boundary itself
  }
  if (method !== 'GET' && csrfToken) headers['X-CSRF-Token'] = csrfToken

  let res: Response
  try {
    res = await fetch(`${base}${path}`, { method, headers, body, credentials: 'include' })
  } catch {
    throw new ApiError(`Could not reach the Module 4 backend at ${base}. Is module4_api.py running?`)
  }
  if (res.status === 401 && !options.expectUnauthorized) unauthorizedHandler?.()
  return res
}

// Original error style, kept so existing screens behave exactly as before.
async function module4PostJson<T>(path: string, body: unknown): Promise<T> {
  const res = await module4Fetch(path, { json: body })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new ApiError(`Backend returned ${res.status}: ${detail}`, res.status)
  }
  return res.json() as Promise<T>
}

// For the login screens: turn the server's {"detail": ...} into a plain sentence.
async function friendlyError(res: Response): Promise<ApiError> {
  let message = `Something went wrong (${res.status}).`
  try {
    const body = await res.json()
    const detail = body?.detail
    if (typeof detail === 'string') {
      message = detail
    } else if (Array.isArray(detail) && detail.length > 0) {
      message = 'Please check what you entered and try again.'
    }
  } catch {
    // not JSON -- keep the generic message
  }
  return new ApiError(message, res.status)
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

// Wraps a REAL, already-built backend endpoint (module4_api.py's
// /session/explanation_level, backed by set_explanation_level() -- FE-4)
// that was fully functional but had ZERO frontend connection until now --
// confirmed live: asking the assistant in plain English to "give a
// shorter answer" did nothing, because that's a content question to
// /session/ask, not a request this endpoint ever got called for.
export function updateExplanationLevel(
  session_id: string,
  explanation_level: 'simple' | 'detailed',
): Promise<{ session_id: string; explanation_level: string }> {
  return module4PostJson('/session/explanation_level', { session_id, explanation_level })
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
    const res = await fetch(`${resolveBaseUrl()}/health`, {
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

  const res = await module4Fetch('/report/transcribe', { form: formData })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new ApiError(`Backend returned ${res.status}: ${detail}`, res.status)
  }

  return res.json() as Promise<TranscribeReportResult>
}

// ── Accounts (step 4b-1) ─────────────────────────────────────────────────────
export type AuthUser = {
  user_id: string
  role: 'patient' | 'doctor' | 'admin'
  display_id: string | null
  email: string
  full_name: string
  status: string
}

export type DoctorInfo = {
  verification_status: string
  license_valid_upto: string | null
} | null

export type MeResult = {
  user: AuthUser
  csrf_token: string
  doctor?: DoctorInfo
}

// Returns null when nobody is logged in (that is a normal answer, not an error).
export async function getMe(): Promise<MeResult | null> {
  const res = await module4Fetch('/auth/me', { expectUnauthorized: true })
  if (res.status === 401) return null
  if (!res.ok) throw await friendlyError(res)
  const me = (await res.json()) as MeResult
  setCsrfToken(me.csrf_token)
  return me
}

async function authPost(path: string, body: unknown): Promise<MeResult> {
  const res = await module4Fetch(path, { json: body, expectUnauthorized: true })
  if (!res.ok) throw await friendlyError(res)
  const result = (await res.json()) as { user: AuthUser; csrf_token: string }
  setCsrfToken(result.csrf_token)
  return { user: result.user, csrf_token: result.csrf_token }
}

export function login(email: string, password: string): Promise<MeResult> {
  return authPost('/auth/login', { email, password })
}

export function registerPatient(email: string, password: string, full_name: string): Promise<MeResult> {
  return authPost('/auth/register/patient', { email, password, full_name })
}

export function registerDoctor(input: {
  email: string
  password: string
  full_name: string
  father_name: string
  pmdc_number: string
}): Promise<MeResult> {
  return authPost('/auth/register/doctor', input)
}

export async function logoutRequest(): Promise<void> {
  const res = await module4Fetch('/auth/logout', { method: 'POST', expectUnauthorized: true })
  setCsrfToken(null)
  // 401 here just means the session was already over -- same end result.
  if (!res.ok && res.status !== 401) throw await friendlyError(res)
}

// ── Saved records and visits (step 4b-2) ─────────────────────────────────────
export type RecordSummary = {
  patient_code: string
  name: string
  created_at: string
  visit_count: number
  last_visit_at: string | null
}

export type DicomMeta = {
  modality: string | null
  view_position: string | null
  rows_px: number | null
  columns_px: number | null
  bits_stored: number | null
  photometric: string | null
  frames: number | null
  transfer_syntax: string | null
  pixel_spacing_row_mm: number | null
  pixel_spacing_col_mm: number | null
  window_center: number | null
  window_width: number | null
  burned_in_annotation: boolean
  size_bytes: number
}

export type VisitListItem = {
  has_dicom?: boolean
  session_id: string
  created_at: string
  has_report: boolean
  version_no: number | null
  diseases_visualized: string[]
}

export type VisitImageKind = 'xray' | 'annotated' | 'comparison'

export type VisitView = {
  visit: { session_id: string; patient_code: string; created_at: string; explanation_level: string }
  report: null | {
    version_no: number
    source: 'ai' | 'doctor_edit'
    created_at: string
    report_text: string
    structured: {
      mode?: AnalysisResult['mode']
      diseases_visualized?: string[]
      diseases_qualified_not_shown?: QualifiedNotShown[]
      findings?: AnalysisResult['findings']
      note?: string | null
      // Added by a doctor edit (step 6a)
      removed_findings?: string[]
      doctor_note?: string | null
      edited_from_version?: number
      // true = the highlighted pictures are still the AI's original (no circle positions were saved)
      images_stale?: boolean
    }
  }
  files: Record<VisitImageKind, boolean>
  dicom?: DicomMeta | null   // technical facts about the kept DICOM original (never patient details)
  read_only: boolean
}

// Niha's server may return the highlighted images either as a full
// "data:image/png;base64,..." string or as bare base64; accept both.
// Returns null (and the image is simply skipped) if it cannot be decoded.
function imageStringToBlob(value: string | null | undefined): Blob | null {
  if (!value) return null
  try {
    let mime = 'image/png'
    let payload = value
    if (value.startsWith('data:')) {
      const comma = value.indexOf(',')
      const header = value.slice(5, comma)
      mime = header.split(';')[0] || 'image/png'
      payload = value.slice(comma + 1)
    }
    const binary = atob(payload)
    const bytes = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
    return new Blob([bytes], { type: mime })
  } catch {
    return null
  }
}

async function failFromResponse(res: Response): Promise<ApiError> {
  const detail = await res.text().catch(() => '')
  return new ApiError(`Backend returned ${res.status}: ${detail}`, res.status)
}

// Stores the AI report, findings and the three images on the server so they
// survive a refresh and show up in "My Records". The server accepts this ONCE
// per visit (a second try is refused with 409).
export async function saveAnalysis(
  sessionId: string,
  result: AnalysisResult,
  xray: File,
  // Set when the X-ray came from a DICOM file: asks the server to keep the original, encrypted.
  dicomToken?: string | null,
): Promise<{ dicomRetained: boolean | null; dicomMessage: string | null }> {
  const { annotated_image_base64, comparison_image_base64, ...rest } = result
  const form = new FormData()
  form.append('analysis_json', JSON.stringify(rest))
  if (dicomToken) form.append('dicom_token', dicomToken)
  form.append('xray', xray, xray.name || 'xray')
  const annotated = imageStringToBlob(annotated_image_base64)
  if (annotated) form.append('annotated', annotated, 'annotated')
  const comparison = imageStringToBlob(comparison_image_base64)
  if (comparison) form.append('comparison', comparison, 'comparison')

  const res = await module4Fetch(`/visits/${encodeURIComponent(sessionId)}/analysis`, { form })
  if (!res.ok) throw await failFromResponse(res)
  const body = (await res.json().catch(() => ({}))) as { dicom_retained?: boolean | null; dicom_message?: string | null }
  return { dicomRetained: body.dicom_retained ?? null, dicomMessage: body.dicom_message ?? null }
}

export async function listRecords(): Promise<RecordSummary[]> {
  const res = await module4Fetch('/records')
  if (!res.ok) throw await failFromResponse(res)
  return ((await res.json()) as { records: RecordSummary[] }).records
}

export async function listVisits(patientCode: string): Promise<VisitListItem[]> {
  const res = await module4Fetch(`/records/${encodeURIComponent(patientCode)}/visits`)
  if (!res.ok) throw await failFromResponse(res)
  return ((await res.json()) as { visits: VisitListItem[] }).visits
}

export async function getVisit(sessionId: string): Promise<VisitView> {
  const res = await module4Fetch(`/visits/${encodeURIComponent(sessionId)}`)
  if (!res.ok) throw await failFromResponse(res)
  return (await res.json()) as VisitView
}

// Images are protected (login + ownership), so they are fetched with the login
// cookie and turned into a local blob: URL that an <img> tag can show.
export async function fetchVisitImageUrl(sessionId: string, kind: VisitImageKind): Promise<string | null> {
  const res = await module4Fetch(`/visits/${encodeURIComponent(sessionId)}/files/${kind}`)
  if (!res.ok) return null
  return URL.createObjectURL(await res.blob())
}

// ── Doctor review (step 5) ───────────────────────────────────────────────────
export type VersionInfo = {
  version_no: number
  source: 'ai' | 'doctor_edit'
  created_at: string
  is_final: boolean
  author: string | null   // display id such as DR-1A2B3C; null for the AI's own version
}

// canvas_px = side of the square (the X-ray padded to a square) that circles are measured on; null if unreadable.
// index_ok is only present on the reply to a save: false means the report was saved but the
// question-answering search could not be refreshed yet (it retries on the next save).
export type DoctorVisitView = VisitView & { versions: VersionInfo[]; canvas_px: number | null; index_ok?: boolean }

// Only a PMDC-verified doctor gets an answer here; everyone else is refused by the SERVER (403).
export async function getDoctorVisit(sessionId: string): Promise<DoctorVisitView> {
  const res = await module4Fetch(`/doctor/visits/${encodeURIComponent(sessionId)}`)
  if (!res.ok) throw await failFromResponse(res)
  return (await res.json()) as DoctorVisitView
}

// ── Doctor editing (step 6a) ─────────────────────────────────────────────────
export type FindingsEdit = {
  base_version_no: number                              // the version the doctor was looking at
  decisions: Record<string, 'confirm' | 'remove'>      // one decision for EVERY current finding
  added: string[]                                      // findings the AI missed (names)
  note: string | null                                  // the doctor's own words
  // Circles the doctor changed, per finding that stays: {finding: [{center_xy, radius_px}]}, in pixels of
  // the square-padded X-ray. Findings not listed keep their circles; an empty list means "no circle".
  regions?: Record<string, { center_xy: [number, number]; radius_px: number }[]>
}

// Turns the server's {"detail": ...} into a plain sentence the doctor can act on.
async function editFailure(res: Response): Promise<ApiError> {
  let message = `The edit could not be saved (${res.status}).`
  try {
    const body = (await res.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') message = body.detail
  } catch {
    /* keep the generic message */
  }
  return new ApiError(message, res.status)
}

// Saves the doctor's review as a NEW report version; the AI's version stays in the history.
// 409 = someone saved a newer version first, 422 = the edit is not valid, 403 = not a verified doctor.
export async function editDoctorFindings(sessionId: string, edit: FindingsEdit): Promise<DoctorVisitView> {
  const res = await module4Fetch(`/doctor/visits/${encodeURIComponent(sessionId)}/edit/findings`, { json: edit })
  if (!res.ok) throw await editFailure(res)
  return (await res.json()) as DoctorVisitView
}

// ── DICOM upload ─────────────────────────────────────────────────────────────
export type DicomConversionInfo = {
  modality: string | null
  view_position: string | null
  original_rows: number
  original_columns: number
  frames: number
  window: 'from_file' | 'automatic' | 'colour'
  warnings: string[]
}

// Sends a DICOM file to the server, which opens it, takes out the picture (adjusted like a
// radiologist's viewer would show it), drops the patient details in the header, and returns a
// plain PNG. Returns that PNG as a File, ready for the normal analysis flow.
export async function convertDicom(file: File): Promise<{ file: File; info: DicomConversionInfo; token: string | null }> {
  const form = new FormData()
  form.append('file', file, file.name || 'upload.dcm')
  const res = await module4Fetch('/dicom/convert', { form })
  if (!res.ok) throw await failFromResponse(res)
  const body = (await res.json()) as { image_base64: string; info: DicomConversionInfo; dicom_token?: string | null }
  const blob = imageStringToBlob(body.image_base64)
  if (!blob) throw new ApiError('The converted DICOM image could not be read.')
  const base = (file.name || 'xray').replace(/\.(dcm|dicom|dic)$/i, '') || 'xray'
  return { file: new File([blob], `${base}.png`, { type: 'image/png' }), info: body.info, token: body.dicom_token ?? null }
}

// Saves the kept DICOM (original, or a de-identified copy) through the browser's normal download.
export async function downloadDicom(sessionId: string, kind: 'original' | 'deidentified'): Promise<void> {
  const res = await module4Fetch(`/visits/${encodeURIComponent(sessionId)}/dicom/${kind}`)
  if (!res.ok) throw await failFromResponse(res)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `visit-${sessionId.slice(0, 8)}${kind === 'deidentified' ? '-deidentified' : ''}.dcm`
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

// Window/level, like a PACS viewer: the same stored DICOM, shown with a different brightness window.
export async function renderDicom(sessionId: string, center: number, width: number, invert?: boolean): Promise<string> {
  const q = new URLSearchParams({ center: String(center), width: String(width) })
  if (invert !== undefined) q.set('invert', String(invert))
  const res = await module4Fetch(`/visits/${encodeURIComponent(sessionId)}/dicom/render?${q}`)
  if (!res.ok) throw await failFromResponse(res)
  return URL.createObjectURL(await res.blob())
}
