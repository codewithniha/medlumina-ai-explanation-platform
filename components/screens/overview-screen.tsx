'use client'

import {
  FileText,
  ScanEye,
  MessagesSquare,
  Pill,
  ArrowRight,
  ShieldCheck,
  HeartHandshake,
  Sparkles,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useApp } from '@/lib/app-context'

const features = [
  {
    icon: FileText,
    title: 'AI Report Generation',
    description:
      'Turns dense radiology reports into a clear, structured summary you can actually understand.',
  },
  {
    icon: ScanEye,
    title: 'Visual Highlighting',
    description:
      'Shows exactly where on your X-ray the finding is, with a simple highlighted region.',
  },
  {
    icon: MessagesSquare,
    title: 'Patient Q&A',
    description:
      'Ask questions in your own words and get calm, plain-language answers any time.',
  },
  {
    icon: Pill,
    title: 'Medicine Explanation',
    description:
      'Explains what each prescribed medicine does and how it relates to your diagnosis.',
  },
]

const trustPoints = [
  { icon: ShieldCheck, label: 'Private & secure by design' },
  { icon: HeartHandshake, label: 'Written for patients, not doctors' },
  { icon: Sparkles, label: 'Clear next-step guidance' },
]

export function OverviewScreen() {
  const { navigate } = useApp()

  return (
    <div>
      {/* Hero */}
      <section className="overflow-hidden rounded-3xl border border-border bg-gradient-to-br from-primary/8 via-card to-accent/40 p-8 sm:p-12">
        <Badge className="mb-5">
          <Sparkles className="size-3.5" />
          AI-powered medical explanations
        </Badge>
        <h1 className="max-w-2xl text-3xl font-bold leading-tight tracking-tight text-foreground text-balance sm:text-4xl">
          Understand your X-ray and diagnosis in plain, calming language.
        </h1>
        <p className="mt-4 max-w-xl text-base leading-relaxed text-muted-foreground text-pretty sm:text-lg">
          MedLumina reads your X-ray image and radiology report, then explains
          what it means for you — without the confusing jargon.
        </p>
        <div className="mt-7 flex flex-col gap-3 sm:flex-row">
          <Button
            size="lg"
            className="h-12 px-6 text-base"
            onClick={() => navigate('input')}
          >
            Get Started
            <ArrowRight className="size-4" />
          </Button>
          <Button
            size="lg"
            variant="outline"
            className="h-12 px-6 text-base"
            onClick={() => navigate('report')}
          >
            View Sample Report
          </Button>
        </div>

        <div className="mt-8 flex flex-wrap gap-x-6 gap-y-3">
          {trustPoints.map((t) => {
            const Icon = t.icon
            return (
              <div
                key={t.label}
                className="flex items-center gap-2 text-sm font-medium text-foreground/80"
              >
                <Icon className="size-4 text-primary" />
                {t.label}
              </div>
            )
          })}
        </div>
      </section>

      {/* Features */}
      <section className="mt-10">
        <h2 className="text-xl font-bold tracking-tight text-foreground">
          What MedLumina does for you
        </h2>
        <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
          Four simple steps from a confusing scan to real understanding.
        </p>
        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          {features.map((f) => {
            const Icon = f.icon
            return (
              <Card
                key={f.title}
                className="transition-shadow hover:shadow-md"
              >
                <CardContent className="flex gap-4 p-6">
                  <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                    <Icon className="size-5" />
                  </div>
                  <div>
                    <h3 className="font-semibold text-card-foreground">
                      {f.title}
                    </h3>
                    <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                      {f.description}
                    </p>
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      </section>

      {/* CTA */}
      <section className="mt-10">
        <Card className="border-primary/20 bg-primary/5">
          <CardContent className="flex flex-col items-start gap-4 p-6 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h3 className="text-lg font-bold text-foreground">
                Ready to understand your results?
              </h3>
              <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                Upload your X-ray and report to get a personalized, easy-to-read
                explanation.
              </p>
            </div>
            <Button
              size="lg"
              className="h-11 shrink-0 px-6"
              onClick={() => navigate('input')}
            >
              Start Analysis
              <ArrowRight className="size-4" />
            </Button>
          </CardContent>
        </Card>
      </section>
    </div>
  )
}
