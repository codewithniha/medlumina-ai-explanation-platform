'use client'

import { AppProvider, useApp } from '@/lib/app-context'
import { ToastProvider } from '@/components/ui/toast'
import { AppShell } from '@/components/app-shell'
import { LandingScreen } from '@/components/screens/landing-screen'
import { InputScreen } from '@/components/screens/input-screen'
import { ReportScreen } from '@/components/screens/report-screen'
import { VisualScreen } from '@/components/screens/visual-screen'
import { QAScreen } from '@/components/screens/qa-screen'
import { MedicineScreen } from '@/components/screens/medicine-screen'
import { SummaryScreen } from '@/components/screens/summary-screen'

function WorkflowScreen() {
  const { screen } = useApp()
  switch (screen) {
    case 'input':
      return <InputScreen />
    case 'report':
      return <ReportScreen />
    case 'visual':
      return <VisualScreen />
    case 'qa':
      return <QAScreen />
    case 'medicine':
      return <MedicineScreen />
    case 'summary':
      return <SummaryScreen />
    default:
      return <InputScreen />
  }
}

function Router() {
  const { screen } = useApp()

  // The landing page is a standalone marketing homepage with no app chrome.
  if (screen === 'landing') {
    return <LandingScreen />
  }

  return (
    <AppShell>
      <WorkflowScreen />
    </AppShell>
  )
}

export default function Page() {
  return (
    <ToastProvider>
      <AppProvider>
        <Router />
      </AppProvider>
    </ToastProvider>
  )
}
