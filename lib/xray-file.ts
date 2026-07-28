'use client'

// Niha's Kaggle backend opens whatever we send it with Pillow (Python's
// image library). Pillow reads JPEG, PNG, WebP, GIF, and BMP with zero
// extra setup -- think of these as the envelope formats her mail room
// already knows how to open. Anything else has to be converted to one of
// these BEFORE it leaves the browser, or her server has to guess how to
// open a format it was never built for -- and iPhones default to saving
// photos as HEIC, which Pillow can't read without a plugin that almost
// certainly isn't installed on her Kaggle notebook.
//
// This file is the single place that decides "is this safe to send
// onward, or does it need converting first" for the X-ray uploader --
// PDF handling lives in pdf-to-image.ts and is called from here.

import { renderPdfFirstPageAsImage } from './pdf-to-image'

const PILLOW_SAFE_TYPES = new Set([
  'image/jpeg',
  'image/png',
  'image/webp',
  'image/gif',
  'image/bmp',
])

// The UI has always SAID "up to 20MB" but nothing ever actually checked
// it -- a patient could pick a 200MB HEIC and heic2any's WASM decoder
// would sit there grinding on it (or freeze the tab) before failing
// badly, instead of a fast, clear rejection up front. Checked first,
// before any conversion work, for exactly that reason.
const MAX_XRAY_FILE_BYTES = 20 * 1024 * 1024 // 20MB, matches the UI copy

function formatMB(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}

function isHeic(file: File): boolean {
  const type = file.type.toLowerCase()
  if (type === 'image/heic' || type === 'image/heif') return true
  // Confirmed common: Windows and some browsers report HEIC files with a
  // generic or empty MIME type (e.g. "application/octet-stream") instead
  // of the real one, especially for photos transferred off an iPhone --
  // the file extension is the more reliable signal in that case.
  const name = file.name.toLowerCase()
  return name.endsWith('.heic') || name.endsWith('.heif')
}

/**
 * Takes whatever file the patient picked or dropped for the X-ray and
 * returns a File guaranteed to be in a format Niha's backend can open.
 *
 * - PDF -> first page rendered to PNG (see pdf-to-image.ts)
 * - HEIC/HEIF (iPhone default) -> converted to JPEG in-browser via
 *   heic2any, which works in any browser (not just Safari) since it
 *   doesn't depend on native OS/browser HEIC support
 * - Already-safe formats (JPEG/PNG/WebP/GIF/BMP) -> returned unchanged;
 *   converting something that already works risks new problems (colour
 *   shifts, lost EXIF rotation) for no benefit
 * - Anything else -> rejects with a clear, patient-safe message, rather
 *   than silently forwarding unknown bytes to the backend and letting it
 *   fail there with a far less clear error
 */
export async function normalizeXrayFile(file: File): Promise<File> {
  if (file.size > MAX_XRAY_FILE_BYTES) {
    throw new Error(
      `This file is ${formatMB(file.size)}, which is over the 20MB limit. Please use a smaller photo or a compressed PDF.`,
    )
  }

  if (file.type === 'application/pdf') {
    return renderPdfFirstPageAsImage(file)
  }

  if (isHeic(file)) {
    const heic2any = (await import('heic2any')).default
    let result: Blob | Blob[]
    try {
      result = await heic2any({ blob: file, toType: 'image/jpeg', quality: 0.9 })
    } catch (err) {
      throw new Error(
        `Could not convert this HEIC photo (${err instanceof Error ? err.message : 'unknown error'}). Try re-saving it as JPEG first (on iPhone: Settings > Camera > Formats > "Most Compatible").`,
      )
    }
    const blob = Array.isArray(result) ? result[0] : result
    const baseName = file.name.replace(/\.(heic|heif)$/i, '') || 'upload'
    return new File([blob], `${baseName}.jpg`, { type: 'image/jpeg' })
  }

  if (PILLOW_SAFE_TYPES.has(file.type.toLowerCase())) {
    return file
  }

  throw new Error(
    `"${file.type || 'unknown format'}" isn't a supported image format. Please use JPEG, PNG, WebP, or export/save this as one of those first.`,
  )
}
