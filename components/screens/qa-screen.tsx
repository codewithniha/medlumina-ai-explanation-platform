'use client'

import { useState, useRef, useEffect } from 'react'
import { Send, Sparkles, Activity } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { PageHeader } from './page-header'
import { cn } from '@/lib/utils'
import {
  initialQA,
  suggestedQuestions,
  cannedResponses,
  type QAMessage,
} from '@/lib/mock-data'

export function QAScreen() {
  const [messages, setMessages] = useState<QAMessage[]>(initialQA)
  const [input, setInput] = useState('')
  const [typing, setTyping] = useState(false)
  const responseIndex = useRef(0)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: 'smooth',
    })
  }, [messages, typing])

  function send(text: string) {
    const trimmed = text.trim()
    if (!trimmed || typing) return
    const patientMsg: QAMessage = {
      id: `q-${Date.now()}`,
      role: 'patient',
      text: trimmed,
    }
    setMessages((prev) => [...prev, patientMsg])
    setInput('')
    setTyping(true)

    // Mocked canned response after a short "typing" delay. No real API call.
    setTimeout(() => {
      const reply =
        cannedResponses[responseIndex.current % cannedResponses.length]
      responseIndex.current += 1
      setMessages((prev) => [
        ...prev,
        { id: `a-${Date.now()}`, role: 'ai', text: reply },
      ])
      setTyping(false)
    }, 1500)
  }

  return (
    <div className="flex h-[calc(100dvh-8rem)] flex-col lg:h-[calc(100dvh-5rem)]">
      <PageHeader
        title="Ask Questions"
        description="Ask anything about your results in your own words. Answers are calm, clear, and easy to follow."
        className="mb-4"
      />

      {/* Messages */}
      <div
        ref={scrollRef}
        className="flex-1 space-y-4 overflow-y-auto rounded-2xl border border-border bg-secondary/30 p-4"
      >
        {messages.map((m) => (
          <div
            key={m.id}
            className={cn(
              'flex items-end gap-2',
              m.role === 'patient' ? 'justify-end' : 'justify-start',
            )}
          >
            {m.role === 'ai' && (
              <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
                <Activity className="size-4" />
              </div>
            )}
            <div
              className={cn(
                'max-w-[80%] rounded-2xl px-4 py-3 text-[15px] leading-relaxed shadow-sm',
                m.role === 'patient'
                  ? 'rounded-br-md bg-primary text-primary-foreground'
                  : 'rounded-bl-md bg-card text-card-foreground',
              )}
            >
              {m.text}
            </div>
          </div>
        ))}

        {typing && (
          <div className="flex items-end gap-2">
            <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
              <Activity className="size-4" />
            </div>
            <div className="flex gap-1 rounded-2xl rounded-bl-md bg-card px-4 py-4 shadow-sm">
              <span className="size-2 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:-0.3s]" />
              <span className="size-2 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:-0.15s]" />
              <span className="size-2 animate-bounce rounded-full bg-muted-foreground/60" />
            </div>
          </div>
        )}
      </div>

      {/* Suggested chips */}
      <div className="mt-3 flex flex-wrap gap-2">
        {suggestedQuestions.map((q) => (
          <button
            key={q}
            onClick={() => send(q)}
            disabled={typing}
            className="flex items-center gap-1.5 rounded-full border border-border bg-card px-3.5 py-1.5 text-sm font-medium text-foreground transition-colors hover:border-primary/40 hover:bg-primary/5 disabled:opacity-50"
          >
            <Sparkles className="size-3.5 text-primary" />
            {q}
          </button>
        ))}
      </div>

      {/* Input */}
      <form
        className="mt-3 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          send(input)
        }}
      >
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
          className="h-12 flex-1 rounded-2xl border border-border bg-background px-4 text-base text-foreground shadow-sm outline-none placeholder:text-muted-foreground focus-visible:border-primary focus-visible:ring-4 focus-visible:ring-primary/15"
        />
        <Button
          type="submit"
          size="icon"
          className="size-12 shrink-0 rounded-2xl"
          disabled={!input.trim() || typing}
          aria-label="Send question"
        >
          <Send className="size-5" />
        </Button>
      </form>
      <p className="mt-2 text-center text-xs text-muted-foreground">
        Sample AI responses for demo purposes. Not a substitute for medical
        advice.
      </p>
    </div>
  )
}
