// Types for the REAL response from the Kaggle backend (server.py), as
// opposed to lib/mock-data.ts which is 100% fictional demo content.

export type AnalysisFinding = {
  positive_prob?: number
  probability?: number
  method?: string
  ctr?: number | null
  source_sentence?: string
  region_count?: number | null
  localized?: boolean | null
  // Circle positions, in pixels of the model's square-padded X-ray (side = canvas_px).
  // Sent by Niha's Module 5 once she adds them; older results do not have them.
  regions?: AnalysisRegion[] | null
  canvas_px?: number | null
  // Set by a doctor edit
  doctor_status?: 'confirmed' | 'added'
}

export type AnalysisRegion = {
  center_xy: [number, number]
  radius_px: number
  bbox_xyxy?: [number, number, number, number] | null
  peak_activation?: number | null
  area_px?: number | null
}

export type QualifiedNotShown = {
  disease: string
  probability: number
}

export type AnalysisResult = {
  mode: 'image_only' | 'image_and_report'
  diseases_visualized: string[]
  diseases_qualified_not_shown: QualifiedNotShown[]
  findings: Record<string, AnalysisFinding>
  report_text: string
  annotated_image_base64: string | null
  comparison_image_base64: string | null
  note?: string
}

export type AnalyzeParams = {
  image: File
  reportText?: string
  probThreshold?: number
  regionThreshold?: number
  maxDiseasesToShow?: number
}
