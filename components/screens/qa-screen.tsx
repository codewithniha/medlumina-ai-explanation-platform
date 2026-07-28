'use client'

import { useState, useRef, useEffect } from 'react'
import {
  Send,
  Sparkles,
  Activity,
  Copy,
  Check,
  Mic,
  Share2,
  ShieldAlert,
  Lightbulb,
  Volume2,
  VolumeX,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { PageHeader } from './page-header'
import { useToast } from '@/components/ui/toast'
import { useApp } from '@/lib/app-context'
import { askQuestion, getSessionHistory, checkHealth } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import {
  suggestedQuestions,
  prescriptionSuggestedQuestions,
  type QAMessage,
} from '@/lib/mock-data'

// Very small markdown-ish renderer: supports **bold** segments.
function RichText({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith('**') && p.endsWith('**') ? (
          <strong key={i} className="font-semibold">
            {p.slice(2, -2)}
          </strong>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  )
}

function MessageBubble({
  message,
  onCopy,
  copied,
  onSpeak,
  isSpeaking,
}: {
  message: QAMessage
  onCopy: (text: string, id: string) => void
  copied: boolean
  onSpeak: (text: string, id: string) => void
  isSpeaking: boolean
}) {
  const isAI = message.role === 'ai'
  return (
    <div
      className={cn(
        'flex items-end gap-2.5',
        isAI ? 'justify-start' : 'justify-end',
      )}
    >
      {isAI && (
        <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-sm">
          <Activity className="size-4" />
        </div>
      )}
      <div className={cn('group max-w-[82%]', isAI ? 'items-start' : 'items-end')}>
        <div
          dir={/[\u0600-\u06FF]/.test(message.text) ? 'rtl' : 'ltr'}
          className={cn(
            'rounded-2xl px-4 py-3 text-[15px] leading-relaxed shadow-sm',
            /[\u0600-\u06FF]/.test(message.text) ? 'text-right' : 'text-left',
            isAI
              ? 'rounded-bl-md border border-border bg-card text-card-foreground'
              : 'rounded-br-md bg-primary text-primary-foreground',
          )}
        >
          <RichText text={message.text} />
        </div>
        {isAI && message.text && (
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5 px-1">
            {message.confidence != null && (
              <span
                className={cn(
                  'rounded-full px-2 py-0.5 text-[10px] font-semibold',
                  message.confidence >= 70
                    ? 'bg-emerald-500/15 text-emerald-400'
                    : message.confidence >= 40
                      ? 'bg-amber-500/15 text-amber-400'
                      : 'bg-red-500/15 text-red-400',
                )}
                title="How strongly this answer matched a real part of your report -- not a guarantee the wording is medically correct."
              >
                Confidence: {message.confidence}%
              </span>
            )}
            {message.confidence == null && message.classification === 'GENERAL_MEDICAL' && (
              <span
                className="rounded-full bg-sky-500/15 px-2 py-0.5 text-[10px] font-semibold text-sky-400"
                title="This is general medical information, not matched against your specific report -- no confidence score applies here."
              >
                General medical information
              </span>
            )}
            <span className="text-[10px] text-muted-foreground">
              AI-generated -- can make mistakes
            </span>
            <button
              onClick={() => onSpeak(message.text, message.id)}
              aria-label={isSpeaking ? 'Stop reading this answer aloud' : 'Listen to this answer'}
              className={cn(
                'flex items-center gap-1 text-[11px] font-medium transition-opacity',
                isSpeaking
                  ? 'text-primary opacity-100'
                  : 'text-muted-foreground opacity-0 hover:text-foreground group-hover:opacity-100 focus-visible:opacity-100',
              )}
            >
              {isSpeaking ? (
                <>
                  <VolumeX className="size-3" /> Stop
                </>
              ) : (
                <>
                  <Volume2 className="size-3" /> Listen
                </>
              )}
            </button>
            <button
              onClick={() => onCopy(message.text, message.id)}
              className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground opacity-0 transition-opacity hover:text-foreground group-hover:opacity-100 focus-visible:opacity-100"
            >
              {copied ? (
                <>
                  <Check className="size-3" /> Copied
                </>
              ) : (
                <>
                  <Copy className="size-3" /> Copy
                </>
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export function QAScreen() {
  const { toast } = useToast()
  const { session, stepEyebrow } = useApp()
  const isPrescription = session.inputMode === 'prescription_only'
  const chips = isPrescription
    ? prescriptionSuggestedQuestions
    : suggestedQuestions
  const [messages, setMessages] = useState<QAMessage[]>([])
  const [input, setInput] = useState('')
  const [typing, setTyping] = useState(false)
  const [streamingId, setStreamingId] = useState<string | null>(null)
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [speakingId, setSpeakingId] = useState<string | null>(null)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [listening, setListening] = useState(false)
  const [voiceLang, setVoiceLang] = useState<'en-US' | 'ur-PK'>('en-US')
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const loadedForSessionId = useRef<string | null>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recognitionRef = useRef<any>(null)

  // Builds the real "here's what I've looked at" opening message --
  // supervisor-requested: must reflect EXACTLY what was provided, never
  // claim to have analyzed an X-ray when only medicines were entered (or
  // any other combination that didn't actually happen). Checks real data
  // presence, not just mode flags -- e.g. session.analysisResult (proof
  // an X-ray was actually successfully processed), not just hasImage
  // (which could be true even if analysis never completed).
  function buildOpeningMessage(): string {
    const parts: string[] = []
    const partsUrdu: string[] = []

    if (session.analysisResult != null) {
      parts.push('X-ray')
      partsUrdu.push('ایکسرے')
    }
    if (session.reportText.trim().length > 0) {
      parts.push("doctor's report")
      partsUrdu.push('ڈاکٹر کی رپورٹ')
    }
    if (session.medicines.length > 0) {
      parts.push('medicines')
      partsUrdu.push('دوائیں')
    }
    if (session.symptoms.trim().length > 0) {
      parts.push('symptoms')
      partsUrdu.push('علامات')
    }

    // Language: base it on whatever real text the patient/doctor actually
    // entered (report or symptoms), same detection approach used
    // throughout the backend -- default to English if nothing to detect
    // from (e.g. prescription-only with no symptoms text).
    const combinedInput = `${session.reportText} ${session.symptoms}`
    const isUrdu = /[\u0600-\u06FF]/.test(combinedInput)

    if (parts.length === 0) {
      return isUrdu
        ? 'میں تیار ہوں۔ آپ کیا پوچھنا چاہیں گے؟'
        : "I'm ready. What would you like to ask me?"
    }

    if (isUrdu) {
      const joined = partsUrdu.join(' اور ')
      return `میں نے آپ کی ${joined} کا جائزہ لے لیا ہے۔ اب پوچھیں۔`
    }

    const joined = parts.join(' and ')
    return `I've analyzed your ${joined}. Ask me anything.`
  }

  // Restores the real conversation from the backend every time this screen
  // is opened with a real session -- so navigating away and coming back
  // doesn't lose every answer MedGemma had already given. log_turn() has
  // always saved every turn on the backend; this just pulls that history
  // back in instead of starting from a blank local-only React state every
  // time the component remounts.
  useEffect(() => {
    if (!session.sessionId) return
    if (loadedForSessionId.current === session.sessionId) return
    loadedForSessionId.current = session.sessionId

    setHistoryLoading(true)
    getSessionHistory(session.sessionId)
      .then((result) => {
        if (result.turns.length === 0) {
          // Brand-new session, no prior conversation -- show the real
          // opening message instead of an empty chat, so the patient
          // knows exactly what the system has (and hasn't) looked at
          // before they ask anything.
          setMessages([
            { id: 'opening', role: 'ai', text: buildOpeningMessage() },
          ])
          return
        }
        const restored: QAMessage[] = result.turns.flatMap((t, i) => [
          { id: `hist-q-${i}`, role: 'patient' as const, text: t.question },
          {
            id: `hist-a-${i}`,
            role: 'ai' as const,
            text: t.answer,
            confidence: t.confidence,
            classification: t.classification,
          },
        ])
        setMessages(restored)
      })
      .catch(() => {
        // Non-fatal -- if history can't be fetched (e.g. backend briefly
        // unreachable), the patient can still ask new questions, they just
        // won't see old ones until a successful reload.
      })
      .finally(() => setHistoryLoading(false))
  }, [session.sessionId])

  // Real "Online" status, not a hardcoded green dot -- confirmed live
  // that the status indicator used to always show Online even when
  // MedGemma was genuinely unreachable, which is actively misleading
  // during a demo. Polls every 20s so it stays accurate if the backend
  // goes down or comes back up mid-session, not just on first load.
  useEffect(() => {
    let cancelled = false
    function poll() {
      checkHealth().then((result) => {
        if (!cancelled) setBackendOnline(result.medgemma_reachable)
      })
    }
    poll()
    const interval = setInterval(poll, 20000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: 'smooth',
    })
  }, [messages, typing])

  // Stop any in-progress speech when leaving this screen -- otherwise an
  // answer would keep reading itself aloud after the patient has already
  // navigated somewhere else, which would be genuinely confusing.
  useEffect(() => {
    return () => {
      if (typeof window !== 'undefined' && window.speechSynthesis) {
        window.speechSynthesis.cancel()
      }
    }
  }, [])

  function copy(text: string, id: string) {
    navigator.clipboard?.writeText(text)
    setCopiedId(id)
    setTimeout(() => setCopiedId(null), 1500)
  }

  // Real text-to-speech for MedGemma's answers, in English or Urdu --
  // supervisor-requested for accessibility: some patients may be blind
  // (can't read the screen at all) or unable to read one of the two
  // languages even if they can read the other. This is a genuine
  // accessibility feature, not a demo flourish, so it needs to actually
  // work, degrade gracefully when unsupported, and never leave two
  // answers talking over each other.
  // getVoices() can return an empty list on the very first call in some
  // browsers, populating asynchronously once the 'voiceschanged' event
  // fires -- this waits for that (with a timeout fallback) so the
  // availability check below isn't done against an empty list that just
  // hasn't loaded yet.
  function getVoicesAsync(): Promise<SpeechSynthesisVoice[]> {
    return new Promise((resolve) => {
      const existing = window.speechSynthesis.getVoices()
      if (existing.length > 0) {
        resolve(existing)
        return
      }
      const timeout = setTimeout(() => resolve(window.speechSynthesis.getVoices()), 1000)
      window.speechSynthesis.onvoiceschanged = () => {
        clearTimeout(timeout)
        resolve(window.speechSynthesis.getVoices())
      }
    })
  }

  async function speak(text: string, id: string) {
    if (typeof window === 'undefined' || !window.speechSynthesis) {
      toast({
        title: 'Voice output not supported',
        description: 'Your browser doesn\u2019t support reading answers aloud. Chrome or Edge work best for this.',
      })
      return
    }

    // Tapping the currently-speaking message again stops it -- toggle,
    // not just "always start a new one".
    if (speakingId === id) {
      window.speechSynthesis.cancel()
      setSpeakingId(null)
      return
    }

    // Only one answer should ever be read aloud at a time -- starting a
    // new one always cancels whatever was playing, so they never overlap.
    window.speechSynthesis.cancel()

    const isUrdu = /[\u0600-\u06FF]/.test(text)

    let speechLang = 'en-US'

    if (isUrdu) {
      // Confirmed live, twice, with two different substitute voices: a
      // device with no real Urdu voice can't read Urdu (Arabic-script)
      // text at all, no matter what `lang` is set to -- it silently
      // skips every Arabic-script character and only speaks whatever
      // Latin-script fragments happen to be embedded in the text (e.g.
      // English medical terms in parentheses). This isn't a `lang`
      // setting problem: a voice's phoneme mapping is tied to the
      // SCRIPT it was trained on, and neither the default fallback nor
      // a Hindi voice can render Arabic script -- that would require a
      // real Urdu-to-Devanagari transliteration step converting the
      // actual characters first, not just relabeling the language. That
      // is real, substantial, separate work, not a quick fix -- so this
      // fails honestly here instead of producing confusing partial
      // audio.
      const voices = await getVoicesAsync()
      const hasUrduVoice = voices.some((v) => v.lang.toLowerCase().startsWith('ur'))

      if (hasUrduVoice) {
        speechLang = 'ur-PK'
      } else {
        toast({
          title: 'Urdu voice not available on this device',
          description:
            'No installed voice can read Urdu script aloud here -- this isn\u2019t fixable by a setting change, it would need a real Urdu-to-Hindi-script conversion step. Please read the text version instead.',
        })
        return
      }
    }

    const utterance = new SpeechSynthesisUtterance(text)
    utterance.lang = speechLang
    utterance.rate = 0.95

    utterance.onstart = () => setSpeakingId(id)
    utterance.onend = () => setSpeakingId(null)
    utterance.onerror = () => {
      setSpeakingId(null)
      toast({
        title: 'Could not read this aloud',
        description: isUrdu
          ? 'Voice output failed for this answer -- try a different browser, or read the text version instead.'
          : 'Something went wrong with voice output. Please try again.',
      })
    }

    window.speechSynthesis.speak(utterance)
  }

  function toggleListening() {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const SpeechRecognitionCtor =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition

    if (!SpeechRecognitionCtor) {
      toast({
        title: 'Voice input not supported',
        description:
          'Your browser doesn\u2019t support voice input. Chrome or Edge work best for this.',
      })
      return
    }

    if (listening) {
      recognitionRef.current?.stop()
      return
    }

    const recognition = new SpeechRecognitionCtor()
    recognition.lang = voiceLang
    recognition.interimResults = false
    recognition.maxAlternatives = 1

    recognition.onstart = () => setListening(true)
    recognition.onerror = () => {
      setListening(false)
      toast({
        title: 'Voice input error',
        description: 'Could not hear you clearly -- please try again or type instead.',
      })
    }
    recognition.onend = () => setListening(false)
    recognition.onresult = (event: any) => {
      const transcript = event.results?.[0]?.[0]?.transcript ?? ''
      if (transcript) setInput((prev) => (prev ? `${prev} ${transcript}` : transcript))
    }

    recognitionRef.current = recognition
    recognition.start()
  }

  function streamReply(
    reply: string,
    confidence: number | null = null,
    classification: QAMessage['classification'] = null,
  ) {
    const id = `a-${Date.now()}`
    setMessages((prev) => [
      ...prev,
      { id, role: 'ai', text: '', confidence, classification },
    ])
    setStreamingId(id)
    const words = reply.split(' ')
    let i = 0
    const timer = setInterval(() => {
      i += 1
      setMessages((prev) =>
        prev.map((m) =>
          m.id === id ? { ...m, text: words.slice(0, i).join(' ') } : m,
        ),
      )
      if (i >= words.length) {
        clearInterval(timer)
        setStreamingId(null)
      }
    }, 45)
  }

  function send(text: string) {
    const trimmed = text.trim()
    if (!trimmed || typing || streamingId) return

    if (!session.sessionId) {
      toast({
        title: 'No active session',
        description: 'Please upload a report first (Step 1) before asking questions.',
      })
      return
    }

    setMessages((prev) => [
      ...prev,
      { id: `q-${Date.now()}`, role: 'patient', text: trimmed },
    ])
    setInput('')
    setTyping(true)

    askQuestion(session.sessionId, trimmed)
      .then((result) => {
        setTyping(false)
        streamReply(result.answer, result.confidence, result.classification)
      })
      .catch((err: unknown) => {
        setTyping(false)
        const message = err instanceof Error ? err.message : 'Something went wrong.'
        toast({ title: 'Could not get an answer', description: message })
        streamReply(
          "Sorry, I couldn't reach the analysis service just now. Please try again in a moment.",
        )
      })
  }

  const busy = typing || !!streamingId

  return (
    <div>
      <PageHeader
        eyebrow={stepEyebrow('qa')}
        title="Ask Questions"
        description="Ask anything about your results in your own words. Answers are calm, clear, and easy to follow."
        className="mb-6"
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Chat */}
        <div className="lg:col-span-8">
          <Card className="flex h-[calc(100dvh-16rem)] flex-col overflow-hidden lg:h-[calc(100dvh-13rem)]">
            {/* Header */}
            <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-3.5">
              <div className="flex items-center gap-2.5">
                <div className="relative flex size-9 items-center justify-center rounded-full bg-primary text-primary-foreground">
                  <Activity className="size-4.5" />
                  <span
                    className={cn(
                      'absolute -bottom-0.5 -right-0.5 size-3 rounded-full border-2 border-card',
                      backendOnline === null
                        ? 'bg-muted-foreground/40'
                        : backendOnline
                          ? 'bg-emerald-400'
                          : 'bg-red-500',
                    )}
                    title={
                      backendOnline === null
                        ? 'Checking connection...'
                        : backendOnline
                          ? 'Connected to MedGemma'
                          : 'MedGemma is unreachable right now'
                    }
                  />
                </div>
                <div>
                  <p className="text-sm font-semibold text-foreground">
                    MedLumina Assistant
                  </p>
                  <p
                    className={cn(
                      'text-[11px]',
                      backendOnline === null
                        ? 'text-muted-foreground'
                        : backendOnline
                          ? 'text-emerald-400'
                          : 'text-red-400',
                    )}
                  >
                    {backendOnline === null ? 'Checking...' : backendOnline ? 'Online' : 'Offline'}
                  </p>
                </div>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="h-8"
                onClick={() => {
                  if (messages.length === 0) {
                    toast({ title: 'Nothing to share yet', description: 'Ask a question first.' })
                    return
                  }
                  const transcript = messages
                    .map((m) => `${m.role === 'patient' ? 'You' : 'MedLumina'}: ${m.text}`)
                    .join('\n\n')

                  if (navigator.share) {
                    navigator
                      .share({ title: 'My MedLumina conversation', text: transcript })
                      .catch(() => {})
                    return
                  }

                  navigator.clipboard
                    ?.writeText(transcript)
                    .then(() =>
                      toast({
                        title: 'Conversation copied',
                        description: 'Your full conversation was copied to the clipboard.',
                      }),
                    )
                    .catch(() =>
                      toast({
                        title: 'Could not copy',
                        description: 'Please select and copy the text manually.',
                      }),
                    )
                }}
              >
                <Share2 className="size-4" />
                Share
              </Button>
            </div>

            {/* Messages */}
            <div
              ref={scrollRef}
              aria-live="polite"
              className="flex-1 space-y-4 overflow-y-auto bg-secondary/20 p-4 sm:p-5"
            >
              {historyLoading && (
                <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-sm text-muted-foreground">
                  <Activity className="size-8 animate-pulse text-primary/40" />
                  <p>Loading your previous conversation...</p>
                </div>
              )}

              {!historyLoading && messages.length === 0 && !typing && (
                <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-sm text-muted-foreground">
                  <Activity className="size-8 text-primary/40" />
                  <p>Ask your first question about your report below,</p>
                  <p>or tap one of the suggestions.</p>
                </div>
              )}

              {messages.map((m) => (
                <MessageBubble
                  key={m.id}
                  message={m}
                  onCopy={copy}
                  copied={copiedId === m.id}
                  onSpeak={speak}
                  isSpeaking={speakingId === m.id}
                />
              ))}

              {typing && (
                <div className="flex items-end gap-2.5">
                  <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
                    <Activity className="size-4" />
                  </div>
                  <div className="flex gap-1 rounded-2xl rounded-bl-md border border-border bg-card px-4 py-4 shadow-sm">
                    <span className="size-2 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:-0.3s]" />
                    <span className="size-2 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:-0.15s]" />
                    <span className="size-2 animate-bounce rounded-full bg-muted-foreground/60" />
                  </div>
                </div>
              )}
            </div>

            {/* Suggested chips */}
            <div className="flex flex-wrap gap-2 border-t border-border px-4 pt-3">
              {chips.map((q) => (
                <button
                  key={q}
                  onClick={() => send(q)}
                  disabled={busy}
                  className="flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1.5 text-[13px] font-medium text-foreground transition-colors hover:border-primary/40 hover:bg-primary/10 disabled:opacity-50"
                >
                  <Sparkles className="size-3.5 text-primary" />
                  {q}
                </button>
              ))}
            </div>

            {/* Input */}
            <form
              className="flex items-center gap-2 p-4"
              onSubmit={(e) => {
                e.preventDefault()
                send(input)
              }}
            >
              <button
                type="button"
                onClick={() =>
                  setVoiceLang((prev) => (prev === 'en-US' ? 'ur-PK' : 'en-US'))
                }
                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-border bg-card text-[11px] font-semibold text-muted-foreground transition-colors hover:text-foreground"
                aria-label="Switch voice input language"
                title={
                  voiceLang === 'en-US'
                    ? 'Voice input language: English (tap to switch to Urdu)'
                    : 'Voice input language: Urdu (tap to switch to English)'
                }
              >
                {voiceLang === 'en-US' ? 'EN' : 'UR'}
              </button>
              <button
                type="button"
                onClick={toggleListening}
                className={cn(
                  'flex size-11 shrink-0 items-center justify-center rounded-xl border transition-colors',
                  listening
                    ? 'animate-pulse border-primary bg-primary text-primary-foreground'
                    : 'border-border bg-card text-muted-foreground hover:text-foreground',
                )}
                aria-label={listening ? 'Stop voice input' : 'Start voice input'}
              >
                <Mic className="size-5" />
              </button>
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (
                    e.key === 'Enter' &&
                    !e.shiftKey &&
                    !e.nativeEvent.isComposing &&
                    e.keyCode !== 229
                  ) {
                    e.preventDefault()
                    send(input)
                  }
                }}
                placeholder="Type your question..."
                className="h-11 flex-1 rounded-xl border border-border bg-background px-4 text-base text-foreground shadow-sm outline-none placeholder:text-muted-foreground focus-visible:border-primary focus-visible:ring-4 focus-visible:ring-primary/15"
              />
              <Button
                type="submit"
                size="icon"
                className="size-11 shrink-0 rounded-xl"
                disabled={!input.trim() || busy}
                aria-label="Send question"
              >
                <Send className="size-5" />
              </Button>
            </form>
          </Card>
        </div>

        {/* Side panel */}
        <div className="space-y-4 lg:col-span-4">
          <Card>
            <CardContent className="p-5">
              <h3 className="flex items-center gap-2 text-sm font-bold text-foreground">
                <Lightbulb className="size-4 text-primary" />
                Things you can ask
              </h3>
              <ul className="mt-3 space-y-2.5 text-sm text-muted-foreground">
                {isPrescription ? (
                  <>
                    <li>What is each medicine for?</li>
                    <li>What condition might these medicines treat?</li>
                    <li>Are there side effects I should know about?</li>
                    <li>Can I take these medicines together?</li>
                  </>
                ) : (
                  <>
                    <li>What does my confidence score mean?</li>
                    <li>How long is the recovery for this?</li>
                    <li>Which medicine treats the infection?</li>
                    <li>What warning signs should I watch for?</li>
                  </>
                )}
              </ul>
            </CardContent>
          </Card>

          {session.patientCode && (
            <Card className="border-primary/25 bg-primary/5">
              <CardContent className="p-5">
                <h3 className="text-sm font-bold text-foreground">Your Patient ID</h3>
                <p className="mt-1 font-mono text-lg font-semibold text-primary">
                  {session.patientCode}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Save this to access this visit again later -- it's the only
                  way to look it up.
                </p>
              </CardContent>
            </Card>
          )}

          <Card className="border-amber-500/25 bg-amber-500/5">
            <CardContent className="flex gap-3 p-5">
              <ShieldAlert className="mt-0.5 size-5 shrink-0 text-amber-400" />
              <div>
                <p className="text-sm font-semibold text-foreground">
                  Medical disclaimer
                </p>
                <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                  MedLumina is an AI assistant, not a doctor -- it can
                  misunderstand your report or make mistakes, especially on
                  medical details. The confidence score under each answer
                  shows how strongly it matched real content in your report,
                  not whether the answer is medically correct. Always confirm
                  important decisions with a qualified doctor.
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
