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
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { PageHeader } from './page-header'
import { useToast } from '@/components/ui/toast'
import { useApp } from '@/lib/app-context'
import { cn } from '@/lib/utils'
import {
  initialQA,
  suggestedQuestions,
  prescriptionSuggestedQuestions,
  cannedResponses,
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
}: {
  message: QAMessage
  onCopy: (text: string, id: string) => void
  copied: boolean
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
          className={cn(
            'rounded-2xl px-4 py-3 text-[15px] leading-relaxed shadow-sm',
            isAI
              ? 'rounded-bl-md border border-border bg-card text-card-foreground'
              : 'rounded-br-md bg-primary text-primary-foreground',
          )}
        >
          <RichText text={message.text} />
        </div>
        {isAI && message.text && (
          <button
            onClick={() => onCopy(message.text, message.id)}
            className="mt-1 flex items-center gap-1 px-1 text-[11px] font-medium text-muted-foreground opacity-0 transition-opacity hover:text-foreground group-hover:opacity-100"
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
  const [messages, setMessages] = useState<QAMessage[]>(initialQA)
  const [input, setInput] = useState('')
  const [typing, setTyping] = useState(false)
  const [streamingId, setStreamingId] = useState<string | null>(null)
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const responseIndex = useRef(0)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: 'smooth',
    })
  }, [messages, typing])

  function copy(text: string, id: string) {
    navigator.clipboard?.writeText(text)
    setCopiedId(id)
    setTimeout(() => setCopiedId(null), 1500)
  }

  function streamReply(reply: string) {
    const id = `a-${Date.now()}`
    setMessages((prev) => [...prev, { id, role: 'ai', text: '' }])
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
    setMessages((prev) => [
      ...prev,
      { id: `q-${Date.now()}`, role: 'patient', text: trimmed },
    ])
    setInput('')
    setTyping(true)
    setTimeout(() => {
      const reply =
        cannedResponses[responseIndex.current % cannedResponses.length]
      responseIndex.current += 1
      setTyping(false)
      streamReply(reply)
    }, 1200)
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
                  <span className="absolute -bottom-0.5 -right-0.5 size-3 rounded-full border-2 border-card bg-emerald-400" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-foreground">
                    MedLumina Assistant
                  </p>
                  <p className="text-[11px] text-emerald-400">Online</p>
                </div>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="h-8"
                onClick={() =>
                  toast({
                    title: 'Conversation shared',
                    description: 'A shareable link was copied (demo only).',
                  })
                }
              >
                <Share2 className="size-4" />
                Share
              </Button>
            </div>

            {/* Messages */}
            <div
              ref={scrollRef}
              className="flex-1 space-y-4 overflow-y-auto bg-secondary/20 p-4 sm:p-5"
            >
              {messages.map((m) => (
                <MessageBubble
                  key={m.id}
                  message={m}
                  onCopy={copy}
                  copied={copiedId === m.id}
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
                  toast({
                    title: 'Voice input',
                    description: 'Voice questions are coming soon.',
                  })
                }
                className="flex size-11 shrink-0 items-center justify-center rounded-xl border border-border bg-card text-muted-foreground transition-colors hover:text-foreground"
                aria-label="Voice input (coming soon)"
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

          <Card className="border-amber-500/25 bg-amber-500/5">
            <CardContent className="flex gap-3 p-5">
              <ShieldAlert className="mt-0.5 size-5 shrink-0 text-amber-400" />
              <div>
                <p className="text-sm font-semibold text-foreground">
                  Medical disclaimer
                </p>
                <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                  These are sample AI responses for a demo. They explain your
                  report in plain language and are not a substitute for advice
                  from a qualified doctor.
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
