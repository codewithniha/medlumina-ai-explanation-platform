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
