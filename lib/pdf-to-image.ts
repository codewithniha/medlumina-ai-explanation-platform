'use client'

// The X-ray analysis model (BioViL-T, running on Niha's Kaggle backend)
// classifies actual image pixels -- it has no idea what a PDF is, the same
// way a photo frame can't display a folded letter. If a patient uploads a
// PDF (e.g. a hospital's digital X-ray report with the image embedded, or
// a scanned page), we render its first page to a real PNG *in the browser*
// before it ever reaches the analyze() call, so from the model's point of
// view nothing has changed -- it still just gets a photo.

let workerConfigured = false

async function getPdfjs() {
  const pdfjsLib = await import('pdfjs-dist')
  if (!workerConfigured) {
    // pdf.js does its actual parsing/rendering work off the main thread in
    // a Web Worker -- this points it at the worker script Next.js will
    // bundle alongside this file.
    pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
      'pdfjs-dist/build/pdf.worker.min.mjs',
      import.meta.url,
    ).toString()
    workerConfigured = true
  }
  return pdfjsLib
}

/**
 * Renders page 1 of a PDF File to a PNG File. Scale 2 is roughly
 * print-quality, well above what the classifier needs.
 *
 * Throws a real Error (with a message safe to show the patient) if the PDF
 * is empty, encrypted in a way the browser can't open, or the browser
 * can't produce a canvas -- these are real failure modes, not
 * hypothetical, and the caller should surface them rather than silently
 * sending a broken file onward to analysis.
 */
export async function renderPdfFirstPageAsImage(file: File): Promise<File> {
  const pdfjsLib = await getPdfjs()
  const buffer = await file.arrayBuffer()

  let pdf
  try {
    pdf = await pdfjsLib.getDocument({ data: buffer }).promise
  } catch (err) {
    throw new Error(
      `Could not open this PDF (${err instanceof Error ? err.message : 'unknown error'}). It may be password-protected or corrupted.`,
    )
  }

  if (pdf.numPages < 1) {
    throw new Error('This PDF has no pages.')
  }

  const page = await pdf.getPage(1)
  const viewport = page.getViewport({ scale: 2 })

  const canvas = document.createElement('canvas')
  canvas.width = viewport.width
  canvas.height = viewport.height
  const context = canvas.getContext('2d')
  if (!context) {
    throw new Error('This browser could not render the PDF page.')
  }

  await page.render({ canvasContext: context, viewport }).promise

  const blob: Blob | null = await new Promise((resolve) =>
    canvas.toBlob(resolve, 'image/png'),
  )
  if (!blob) {
    throw new Error('Could not convert the PDF page to an image.')
  }

  const baseName = file.name.replace(/\.pdf$/i, '') || 'upload'
  return new File([blob], `${baseName}-page1.png`, { type: 'image/png' })
}
