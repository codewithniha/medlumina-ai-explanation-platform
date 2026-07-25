import type { AnalysisResult } from './analysis-types'
import type { Finding, MockReport } from './mock-data'

// 'pleural_effusion' -> 'Pleural Effusion' — mirrors Module 2's own
// inference.py display_name() so labels match what the model actually names.
function displayName(disease: string): string {
  return disease.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function probabilityOf(finding: AnalysisResult['findings'][string]): number {
  return finding.positive_prob ?? finding.probability ?? 0
}

// UI heuristic only — Module 2/5 don't output a severity grade, so this
// buckets the top finding's probability into the three labels the existing
// report UI already has a slot for.
function severityFromProbability(p: number): MockReport['severity'] {
  if (p >= 0.85) return 'Severe'
  if (p >= 0.65) return 'Moderate'
  return 'Mild'
}

// Module 2's generate() returns one formatted text blob:
//   "...FINDINGS:\n<findings>\n\nIMPRESSION:\n<impression>\n"
// Split it back into sections for the existing Impression / Findings UI.
function splitReportText(reportText: string): { findingsSection: string; impressionSection: string } {
  const findingsMatch = reportText.match(/FINDINGS:\s*([\s\S]*?)\n\nIMPRESSION:/)
  const impressionMatch = reportText.match(/IMPRESSION:\s*([\s\S]*)$/)
  return {
    findingsSection: findingsMatch?.[1]?.trim() ?? reportText.trim(),
    impressionSection: impressionMatch?.[1]?.trim() ?? '',
  }
}

export function mapAnalysisToReport(result: AnalysisResult): MockReport {
  const diseases = result.diseases_visualized
  const entries = diseases.map((d) => ({ disease: d, finding: result.findings[d] })).filter((e) => e.finding)

  const topProb = entries.length ? Math.max(...entries.map((e) => probabilityOf(e.finding))) : 0
  const { findingsSection, impressionSection } = splitReportText(result.report_text || '')

  const findings: Finding[] =
    entries.length > 0
      ? entries.map(({ disease, finding }) => {
          const prob = probabilityOf(finding)
          const detailParts = [
            `Model confidence ${Math.round(prob * 100)}%`,
            finding.method ? `via ${finding.method} scoring` : null,
          ]
            .filter(Boolean)
            .join(' ')
          const detail = finding.source_sentence
            ? `Reported by your doctor: "${finding.source_sentence}". ${detailParts}.`
            : `${detailParts}.${
                finding.localized === false ? ' No single region cleared the localization threshold strongly enough to circle.' : ''
              }`
          return {
            region: displayName(disease),
            detail,
            status: 'attention' as const,
            tags: [
              finding.method ?? 'model finding',
              finding.region_count ? `${finding.region_count} region(s) marked` : 'not localized',
            ],
          }
        })
      : [
          {
            region: 'Overall screening',
            detail:
              result.mode === 'image_and_report'
                ? 'None of the conditions this system screens for were found mentioned in the report text you provided.'
                : 'No screened condition scored above the reporting threshold on this image.',
            status: 'normal' as const,
            tags: ['No findings'],
          },
        ]

  const diagnosis =
    diseases.length > 0
      ? diseases.map(displayName).join(', ')
      : result.mode === 'image_and_report'
        ? 'No registered findings matched in the report'
        : 'No significant findings detected'

  return {
    confidence: Math.round(topProb * 100) || 0,
    severity: severityFromProbability(topProb),
    diagnosis,
    findings,
    impression:
      impressionSection ||
      (result.mode === 'image_and_report'
        ? 'Diagnosis taken directly from the report you provided; this system only localizes and visualizes it on the image.'
        : 'Automated screening result — review by a qualified radiologist is required.'),
    plainSummary:
      findingsSection ||
      result.report_text ||
      'No additional detail was returned for this analysis.',
    visualCaption:
      diseases.length > 0
        ? `The annotated image circles the region(s) the model associated with ${diseases
            .map(displayName)
            .join(', ')}, with an arrow and label on the most prominent area for each.`
        : 'No regions were circled since no finding qualified for visualization.',
    // Not used when a real annotated image is available (see visual-screen.tsx) —
    // kept only so this object satisfies MockReport's shape.
    heatmap: { top: 52, left: 30, width: 22, height: 22 },
  }
}
