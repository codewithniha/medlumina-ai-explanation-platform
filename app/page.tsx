'use client'

import { AppProvider, useApp } from '@/lib/app-context'
import { ToastProvider } from '@/components/ui/toast'
import { AppShell } from '@/components/app-shell'
import { OverviewScreen } from '@/components/screens/overview-screen'
import { InputScreen } from '@/components/screens/input-screen'
import { ReportScreen } from '@/components/screens/report-screen'
import { VisualScreen } from '@/components/screens/visual-screen'
import { QAScreen } from '@/components/screens/qa-screen'
import { MedicineScreen } from '@/components/screens/medicine-screen'
import { SummaryScreen } from '@/components/screens/summary-screen'

function CurrentScreen() {
  const { screen } = useApp()
  switch (screen) {
    case 'overview':
      return <OverviewScreen />
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
      return <OverviewScreen />
  }
}

export default function Page() {
  return (
    <ToastProvider>
      <AppProvider>
        <AppShell>
          <CurrentScreen />
        </AppShell>
      </AppProvider>
    </ToastProvider>
  )
}
