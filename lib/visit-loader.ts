import type { AnalysisResult } from './analysis-types'
import type { InputMode } from './app-context'
import { fetchVisitImageUrl, getVisit, type VisitView } from './api-client'

// Turns a visit saved on the SERVER back into the exact shape the report and
// visual-explanation screens already know how to draw. Those screens read
// analysisResult.annotated_image_base64 / comparison_image_base64 straight into
// <img src>, and a blob: URL works there just like a data: URL does, so the
// existing screens need no changes -- and a saved visit is drawn by the very
// same code as a fresh one.
export type LoadedVisit = {
  view: VisitView
  analysisResult: AnalysisResult | null
  imagePreviewUrl: string | null
  inputMode: InputMode
}

export async function loadVisitForDisplay(sessionId: string): Promise<LoadedVisit> {
  const view = await getVisit(sessionId)
  if (!view.report) {
    return { view, analysisResult: null, imagePreviewUrl: null, inputMode: 'prescription_only' }
  }

  const [xray, annotated, comparison] = await Promise.all([
    view.files.xray ? fetchVisitImageUrl(sessionId, 'xray') : Promise.resolve(null),
    view.files.annotated ? fetchVisitImageUrl(sessionId, 'annotated') : Promise.resolve(null),
    view.files.comparison ? fetchVisitImageUrl(sessionId, 'comparison') : Promise.resolve(null),
  ])

  const s = view.report.structured
  const mode = s.mode ?? 'image_only'
  const analysisResult: AnalysisResult = {
    mode,
    diseases_visualized: s.diseases_visualized ?? [],
    diseases_qualified_not_shown: s.diseases_qualified_not_shown ?? [],
    findings: s.findings ?? {},
    report_text: view.report.report_text,
    annotated_image_base64: annotated,
    comparison_image_base64: comparison,
    note: s.note ?? undefined,
  }
  return {
    view,
    analysisResult,
    imagePreviewUrl: xray,
    inputMode: mode === 'image_and_report' ? 'xray_report' : 'xray_only',
  }
}
