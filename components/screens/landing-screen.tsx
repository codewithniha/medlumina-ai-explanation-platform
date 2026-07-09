'use client'

import { useState } from 'react'
import {
  FileText,
  ScanEye,
  MessagesSquare,
  Pill,
  ArrowRight,
  ShieldCheck,
  HeartHandshake,
  Sparkles,
  UploadCloud,
  ClipboardCheck,
  Lock,
  EyeOff,
  Server,
  Star,
  ChevronDown,
  Stethoscope,
  Brain,
  Clock,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { BrandLogo } from '@/components/brand-logo'
import { useApp } from '@/lib/app-context'
import { testimonials, faqItems } from '@/lib/mock-data'
import { cn } from '@/lib/utils'

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
      'Shows exactly where on your X-ray the finding is, with an interactive highlighted region.',
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

const steps = [
  {
    icon: UploadCloud,
    title: 'Upload your X-ray',
    description:
      'Add your chest X-ray image along with any report text, medicines, or symptoms.',
  },
  {
    icon: Brain,
    title: 'AI reads the image',
    description:
      'MedLumina analyzes the scan and identifies the key regions and findings.',
  },
  {
    icon: FileText,
    title: 'Get a plain report',
    description:
      'Medical jargon is translated into a calm, structured, patient-friendly summary.',
  },
  {
    icon: ClipboardCheck,
    title: 'Understand next steps',
    description:
      'See your medicines, connected symptoms, and clear guidance on what to do next.',
  },
]

const benefits = [
  {
    icon: Brain,
    title: 'Genuinely intelligent',
    description:
      'Findings, confidence scores, and visual highlights work together to build real understanding.',
  },
  {
    icon: HeartHandshake,
    title: 'Human-centered',
    description:
      'Written for patients, not clinicians — calm, reassuring, and free of intimidating jargon.',
  },
  {
    icon: Clock,
    title: 'Instant clarity',
    description:
      'Get an easy-to-read explanation of your results in moments, any time of day.',
  },
  {
    icon: Stethoscope,
    title: 'Clinically grounded',
    description:
      'Every explanation states its confidence and reminds you to confirm with your doctor.',
  },
]

const privacyPoints = [
  {
    icon: Lock,
    title: 'Encrypted by design',
    description:
      'A production deployment would encrypt data in transit and at rest with strict access control.',
  },
  {
    icon: EyeOff,
    title: 'Nothing sold or shared',
    description:
      'Your medical information is never used for advertising or shared with third parties.',
  },
  {
    icon: Server,
    title: 'Demo runs locally',
    description:
      'This prototype uses fictional sample data only — nothing is stored on a server.',
  },
]

function MarketingNav() {
  const { navigate } = useApp()
  return (
    <header className="sticky top-0 z-50 border-b border-border/60 bg-background/70 backdrop-blur-xl">
      <div className="mx-auto flex h-16 w-full max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <BrandLogo />
        <nav className="hidden items-center gap-8 md:flex">
          <a
            href="#features"
            className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            Features
          </a>
          <a
            href="#how-it-works"
            className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            How it works
          </a>
          <a
            href="#privacy"
            className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            Privacy
          </a>
          <a
            href="#faq"
            className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            FAQ
          </a>
        </nav>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            className="hidden h-10 px-4 sm:inline-flex"
            onClick={() => navigate('report')}
          >
            View sample
          </Button>
          <Button className="h-10 px-5" onClick={() => navigate('input')}>
            Get Started
            <ArrowRight className="size-4" />
          </Button>
        </div>
      </div>
    </header>
  )
}

function Hero() {
  const { navigate } = useApp()
  return (
    <section className="relative overflow-hidden">
      {/* Animated background */}
      <div className="pointer-events-none absolute inset-0 bg-grid [mask-image:radial-gradient(ellipse_70%_60%_at_50%_0%,#000_60%,transparent_100%)]" />
      <div className="pointer-events-none absolute -top-40 left-1/2 size-[42rem] -translate-x-1/2 rounded-full bg-primary/15 blur-[120px] animate-pulse-glow" />
      <div className="pointer-events-none absolute top-40 right-0 size-96 rounded-full bg-chart-2/10 blur-[120px]" />

      <div className="mx-auto grid w-full max-w-7xl grid-cols-1 items-center gap-12 px-4 py-20 sm:px-6 lg:grid-cols-12 lg:gap-8 lg:px-8 lg:py-28">
        <div className="lg:col-span-6">
          <Badge className="mb-6 border border-primary/20 bg-primary/10 px-3 py-1.5">
            <Sparkles className="size-3.5" />
            AI-powered medical explanations
          </Badge>
          <h1 className="text-4xl font-bold leading-[1.08] tracking-tight text-foreground text-balance sm:text-5xl lg:text-6xl">
            Understand your X-ray in plain, calming language.
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-muted-foreground text-pretty">
            MedLumina reads your chest X-ray and radiology report, then explains
            what it means for you — without the confusing medical jargon.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <Button
              className="h-12 px-6 text-base"
              onClick={() => navigate('input')}
            >
              Analyze my X-ray
              <ArrowRight className="size-4" />
            </Button>
            <Button
              variant="outline"
              className="h-12 px-6 text-base"
              onClick={() => navigate('report')}
            >
              View sample report
            </Button>
          </div>
          <div className="mt-10 flex flex-wrap gap-x-6 gap-y-3">
            {[
              { icon: ShieldCheck, label: 'Private & secure by design' },
              { icon: HeartHandshake, label: 'Written for patients' },
              { icon: Sparkles, label: 'Clear next-step guidance' },
            ].map((t) => {
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
        </div>

        {/* Illustration */}
        <div className="lg:col-span-6">
          <div className="relative mx-auto max-w-lg">
            <div className="absolute -inset-4 rounded-[2rem] bg-primary/10 blur-2xl" />
            <div className="relative overflow-hidden rounded-3xl border border-border glass shadow-2xl">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src="/hero-medical-ai.png"
                alt="Abstract 3D illustration of a glowing ribcage analyzed by AI"
                className="aspect-square w-full object-cover"
              />
              {/* Floating stat cards */}
              <div className="absolute left-4 top-4 flex items-center gap-2 rounded-xl border border-border glass px-3 py-2 animate-float">
                <div className="flex size-8 items-center justify-center rounded-lg bg-primary/15 text-primary">
                  <ScanEye className="size-4" />
                </div>
                <div>
                  <p className="text-xs font-semibold text-foreground">
                    Analyzing region
                  </p>
                  <p className="text-[10px] text-muted-foreground">
                    Lower left lung field
                  </p>
                </div>
              </div>
              <div
                className="absolute bottom-4 right-4 flex items-center gap-2 rounded-xl border border-border glass px-3 py-2 animate-float"
                style={{ animationDelay: '1.5s' }}
              >
                <div className="flex size-8 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-400">
                  <ShieldCheck className="size-4" />
                </div>
                <div>
                  <p className="text-xs font-semibold text-foreground">
                    87% confidence
                  </p>
                  <p className="text-[10px] text-muted-foreground">
                    Mild finding detected
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Trust bar */}
      <div className="border-y border-border/60 bg-card/30">
        <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center justify-center gap-x-10 gap-y-3 px-4 py-5 text-center sm:px-6 lg:px-8">
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Built for patients, families & clinicians
          </p>
          <div className="flex flex-wrap items-center justify-center gap-x-8 gap-y-2 text-sm font-semibold text-foreground/70">
            <span>Patient-first</span>
            <span className="text-border">•</span>
            <span>Explainable AI</span>
            <span className="text-border">•</span>
            <span>Radiology-aware</span>
            <span className="text-border">•</span>
            <span>Privacy by design</span>
          </div>
        </div>
      </div>
    </section>
  )
}

function SectionHeading({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string
  title: string
  description?: string
}) {
  return (
    <div className="mx-auto max-w-2xl text-center">
      <p className="text-sm font-semibold text-primary">{eyebrow}</p>
      <h2 className="mt-2 text-3xl font-bold tracking-tight text-foreground text-balance sm:text-4xl">
        {title}
      </h2>
      {description && (
        <p className="mt-4 text-lg leading-relaxed text-muted-foreground text-pretty">
          {description}
        </p>
      )}
    </div>
  )
}

function Features() {
  return (
    <section id="features" className="scroll-mt-20 py-20 sm:py-28">
      <div className="mx-auto w-full max-w-7xl px-4 sm:px-6 lg:px-8">
        <SectionHeading
          eyebrow="Features"
          title="Everything you need to understand your results"
          description="Four connected tools that take you from a confusing scan to genuine clarity."
        />
        <div className="mt-14 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {features.map((f) => {
            const Icon = f.icon
            return (
              <div
                key={f.title}
                className="group rounded-2xl border border-border bg-card p-6 transition-all duration-300 hover:-translate-y-1 hover:border-primary/40 hover:shadow-[0_12px_40px_-12px_var(--color-primary)]"
              >
                <div className="flex size-12 items-center justify-center rounded-xl bg-primary/10 text-primary transition-colors group-hover:bg-primary group-hover:text-primary-foreground">
                  <Icon className="size-6" />
                </div>
                <h3 className="mt-5 text-base font-semibold text-card-foreground">
                  {f.title}
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                  {f.description}
                </p>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}

function HowItWorks() {
  return (
    <section
      id="how-it-works"
      className="scroll-mt-20 border-y border-border/60 bg-card/20 py-20 sm:py-28"
    >
      <div className="mx-auto w-full max-w-7xl px-4 sm:px-6 lg:px-8">
        <SectionHeading
          eyebrow="How it works"
          title="From upload to understanding in four steps"
        />
        <div className="relative mt-16 grid grid-cols-1 gap-8 sm:grid-cols-2 lg:grid-cols-4">
          {/* Connecting line */}
          <div className="pointer-events-none absolute left-0 right-0 top-6 hidden h-px bg-gradient-to-r from-transparent via-primary/40 to-transparent lg:block" />
          {steps.map((s, i) => {
            const Icon = s.icon
            return (
              <div key={s.title} className="relative flex flex-col items-center text-center">
                <div className="relative z-10 flex size-12 items-center justify-center rounded-full border border-primary/30 bg-background text-primary shadow-[0_0_0_6px_var(--color-background)]">
                  <Icon className="size-5" />
                </div>
                <span className="mt-4 text-xs font-bold uppercase tracking-wider text-primary">
                  Step {i + 1}
                </span>
                <h3 className="mt-1 text-base font-semibold text-foreground">
                  {s.title}
                </h3>
                <p className="mt-2 max-w-xs text-sm leading-relaxed text-muted-foreground">
                  {s.description}
                </p>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}

function Benefits() {
  return (
    <section className="py-20 sm:py-28">
      <div className="mx-auto w-full max-w-7xl px-4 sm:px-6 lg:px-8">
        <SectionHeading
          eyebrow="Why MedLumina"
          title="Premium care, made understandable"
        />
        <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-2">
          {benefits.map((b) => {
            const Icon = b.icon
            return (
              <div
                key={b.title}
                className="flex gap-5 rounded-2xl border border-border bg-card p-7 transition-colors hover:border-primary/30"
              >
                <div className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                  <Icon className="size-6" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-card-foreground">
                    {b.title}
                  </h3>
                  <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                    {b.description}
                  </p>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}

function Privacy() {
  return (
    <section
      id="privacy"
      className="scroll-mt-20 border-y border-border/60 bg-card/20 py-20 sm:py-28"
    >
      <div className="mx-auto grid w-full max-w-7xl grid-cols-1 items-start gap-12 px-4 sm:px-6 lg:grid-cols-12 lg:px-8">
        <div className="lg:col-span-5">
          <Badge className="mb-5 border border-primary/20 bg-primary/10">
            <ShieldCheck className="size-3.5" />
            Privacy first
          </Badge>
          <h2 className="text-3xl font-bold tracking-tight text-foreground text-balance sm:text-4xl">
            Your medical data stays yours
          </h2>
          <p className="mt-4 text-lg leading-relaxed text-muted-foreground text-pretty">
            MedLumina is built around the principle that understanding your
            health should never cost you your privacy.
          </p>
        </div>
        <div className="grid gap-4 lg:col-span-7">
          {privacyPoints.map((p) => {
            const Icon = p.icon
            return (
              <div
                key={p.title}
                className="flex gap-4 rounded-2xl border border-border bg-card p-6"
              >
                <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                  <Icon className="size-5" />
                </div>
                <div>
                  <h3 className="font-semibold text-card-foreground">
                    {p.title}
                  </h3>
                  <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                    {p.description}
                  </p>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}

function Testimonials() {
  return (
    <section className="py-20 sm:py-28">
      <div className="mx-auto w-full max-w-7xl px-4 sm:px-6 lg:px-8">
        <SectionHeading
          eyebrow="Loved by patients"
          title="Clarity people can feel"
        />
        <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-3">
          {testimonials.map((t) => (
            <figure
              key={t.name}
              className="flex flex-col rounded-2xl border border-border bg-card p-7"
            >
              <div className="flex gap-0.5 text-primary">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Star key={i} className="size-4 fill-current" />
                ))}
              </div>
              <blockquote className="mt-4 flex-1 text-[15px] leading-relaxed text-foreground/90 text-pretty">
                &ldquo;{t.quote}&rdquo;
              </blockquote>
              <figcaption className="mt-6 border-t border-border pt-4">
                <p className="text-sm font-semibold text-foreground">
                  {t.name}
                </p>
                <p className="text-xs text-muted-foreground">{t.role}</p>
              </figcaption>
            </figure>
          ))}
        </div>
      </div>
    </section>
  )
}

function FAQ() {
  const [open, setOpen] = useState<number | null>(0)
  return (
    <section
      id="faq"
      className="scroll-mt-20 border-t border-border/60 bg-card/20 py-20 sm:py-28"
    >
      <div className="mx-auto w-full max-w-3xl px-4 sm:px-6 lg:px-8">
        <SectionHeading
          eyebrow="FAQ"
          title="Questions, answered clearly"
        />
        <div className="mt-12 space-y-3">
          {faqItems.map((item, i) => {
            const isOpen = open === i
            return (
              <div
                key={item.question}
                className="overflow-hidden rounded-2xl border border-border bg-card"
              >
                <button
                  onClick={() => setOpen(isOpen ? null : i)}
                  aria-expanded={isOpen}
                  className="flex w-full items-center justify-between gap-4 px-6 py-5 text-left"
                >
                  <span className="text-base font-semibold text-foreground">
                    {item.question}
                  </span>
                  <ChevronDown
                    className={cn(
                      'size-5 shrink-0 text-muted-foreground transition-transform duration-300',
                      isOpen && 'rotate-180 text-primary',
                    )}
                  />
                </button>
                <div
                  className={cn(
                    'grid transition-all duration-300 ease-out',
                    isOpen
                      ? 'grid-rows-[1fr] opacity-100'
                      : 'grid-rows-[0fr] opacity-0',
                  )}
                >
                  <div className="overflow-hidden">
                    <p className="px-6 pb-5 text-[15px] leading-relaxed text-muted-foreground text-pretty">
                      {item.answer}
                    </p>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}

function FinalCTA() {
  const { navigate } = useApp()
  return (
    <section className="py-20 sm:py-28">
      <div className="mx-auto w-full max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="relative overflow-hidden rounded-3xl border border-primary/20 bg-gradient-to-br from-primary/15 via-card to-card p-10 text-center sm:p-16">
          <div className="pointer-events-none absolute -top-24 left-1/2 size-96 -translate-x-1/2 rounded-full bg-primary/20 blur-[100px]" />
          <div className="relative">
            <h2 className="mx-auto max-w-2xl text-3xl font-bold tracking-tight text-foreground text-balance sm:text-4xl">
              Ready to understand your results?
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-lg leading-relaxed text-muted-foreground text-pretty">
              Upload your X-ray and report to get a personalized, easy-to-read
              explanation in moments.
            </p>
            <Button
              className="mt-8 h-12 px-8 text-base"
              onClick={() => navigate('input')}
            >
              Start your analysis
              <ArrowRight className="size-4" />
            </Button>
          </div>
        </div>
      </div>
    </section>
  )
}

function Footer() {
  const { navigate } = useApp()
  return (
    <footer className="border-t border-border/60 bg-background">
      <div className="mx-auto w-full max-w-7xl px-4 py-14 sm:px-6 lg:px-8">
        <div className="flex flex-col justify-between gap-10 lg:flex-row">
          <div className="max-w-sm">
            <BrandLogo />
            <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
              An AI companion that translates complex chest X-ray findings into
              clear, calm language patients can understand.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-10 sm:grid-cols-3">
            <div>
              <p className="text-sm font-semibold text-foreground">Product</p>
              <ul className="mt-4 space-y-3 text-sm text-muted-foreground">
                <li>
                  <button
                    onClick={() => navigate('input')}
                    className="transition-colors hover:text-foreground"
                  >
                    Upload X-ray
                  </button>
                </li>
                <li>
                  <button
                    onClick={() => navigate('report')}
                    className="transition-colors hover:text-foreground"
                  >
                    Sample report
                  </button>
                </li>
                <li>
                  <button
                    onClick={() => navigate('qa')}
                    className="transition-colors hover:text-foreground"
                  >
                    Ask questions
                  </button>
                </li>
              </ul>
            </div>
            <div>
              <p className="text-sm font-semibold text-foreground">Company</p>
              <ul className="mt-4 space-y-3 text-sm text-muted-foreground">
                <li>
                  <a href="#features" className="transition-colors hover:text-foreground">
                    Features
                  </a>
                </li>
                <li>
                  <a href="#privacy" className="transition-colors hover:text-foreground">
                    Privacy
                  </a>
                </li>
                <li>
                  <a href="#faq" className="transition-colors hover:text-foreground">
                    FAQ
                  </a>
                </li>
              </ul>
            </div>
            <div>
              <p className="text-sm font-semibold text-foreground">Legal</p>
              <ul className="mt-4 space-y-3 text-sm text-muted-foreground">
                <li>Terms</li>
                <li>Privacy policy</li>
                <li>Disclaimer</li>
              </ul>
            </div>
          </div>
        </div>
        <div className="mt-12 border-t border-border pt-8">
          <p className="text-xs leading-relaxed text-muted-foreground">
            MedLumina is a Final Year Project demo. All reports, images,
            medicines, and answers shown are fictional sample data and must not
            be used for real medical decisions. Always consult a qualified
            healthcare professional.
          </p>
          <p className="mt-4 text-xs text-muted-foreground">
            © {new Date().getFullYear()} MedLumina. For demonstration purposes only.
          </p>
        </div>
      </div>
    </footer>
  )
}

export function LandingScreen() {
  return (
    <div className="min-h-dvh bg-background">
      <MarketingNav />
      <main>
        <Hero />
        <Features />
        <HowItWorks />
        <Benefits />
        <Privacy />
        <Testimonials />
        <FAQ />
        <FinalCTA />
      </main>
      <Footer />
    </div>
  )
}
