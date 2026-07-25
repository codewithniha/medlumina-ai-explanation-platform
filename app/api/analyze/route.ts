import { NextRequest, NextResponse } from 'next/server'

// Raise this if your Vercel plan allows it (Hobby caps function duration at
// 10s by default; Pro allows up to 300s). BioViL-T inference on a Kaggle GPU
// typically takes a few seconds per image once the model is loaded, but give
// it headroom for a cold ngrok tunnel.
export const maxDuration = 60

export async function POST(request: NextRequest) {
  const backendUrl = process.env.KAGGLE_BACKEND_URL

  if (!backendUrl) {
    return NextResponse.json(
      {
        error:
          'KAGGLE_BACKEND_URL is not set. Add it in Vercel > Project > Settings > Environment Variables, pointing at your Kaggle notebook\'s ngrok URL (see backend/KAGGLE_SETUP.md).',
      },
      { status: 500 },
    )
  }

  let incomingForm: FormData
  try {
    incomingForm = await request.formData()
  } catch {
    return NextResponse.json({ error: 'Expected multipart/form-data with an "image" field.' }, { status: 400 })
  }

  const image = incomingForm.get('image')
  if (!(image instanceof Blob)) {
    return NextResponse.json({ error: 'Missing "image" file in the request.' }, { status: 400 })
  }

  // Rebuild the form to forward — fetch's FormData can carry the Blob straight
  // through without re-reading it into memory as base64.
  const outgoingForm = new FormData()
  outgoingForm.append('image', image, (image as File).name ?? 'upload.png')
  for (const field of ['report_text', 'prob_threshold', 'region_threshold', 'max_diseases_to_show']) {
    const value = incomingForm.get(field)
    if (value != null) outgoingForm.append(field, value as string)
  }

  let backendRes: Response
  try {
    backendRes = await fetch(`${backendUrl.replace(/\/$/, '')}/analyze`, {
      method: 'POST',
      body: outgoingForm,
      // The notebook's ngrok tunnel can go idle/cold between demo sessions.
      signal: AbortSignal.timeout(55_000),
    })
  } catch (err) {
    return NextResponse.json(
      {
        error:
          'Could not reach the Kaggle backend. Make sure the notebook is running, the ngrok tunnel is live, and KAGGLE_BACKEND_URL in Vercel matches the current ngrok URL.',
        detail: err instanceof Error ? err.message : String(err),
      },
      { status: 502 },
    )
  }

  const text = await backendRes.text()
  if (!backendRes.ok) {
    return NextResponse.json(
      { error: 'The backend returned an error.', detail: text },
      { status: backendRes.status },
    )
  }

  try {
    const data = JSON.parse(text)
    return NextResponse.json(data)
  } catch {
    return NextResponse.json({ error: 'Backend returned a non-JSON response.', detail: text }, { status: 502 })
  }
}
