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
