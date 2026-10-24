'use client'

import { Loader2 } from 'lucide-react'
import { AppProvider, useApp } from '@/lib/app-context'
import { AuthProvider, useAuth } from '@/lib/auth-context'
import { ToastProvider } from '@/components/ui/toast'
import { AppShell } from '@/components/app-shell'
import { LandingScreen } from '@/components/screens/landing-screen'
import { AdminNoticeScreen, AuthScreen, DoctorNotActiveScreen } from '@/components/screens/auth-screen'
import { InputScreen } from '@/components/screens/input-screen'
import { ReportScreen } from '@/components/screens/report-screen'
import { VisualScreen } from '@/components/screens/visual-screen'
import { QAScreen } from '@/components/screens/qa-screen'
import { MedicineScreen } from '@/components/screens/medicine-screen'
import { SummaryScreen } from '@/components/screens/summary-screen'
import { RecordsScreen } from '@/components/screens/records-screen'
import { DoctorScreen } from '@/components/screens/doctor-screen'

function WorkflowScreen() {
  const { screen } = useApp()
  const { user } = useAuth()
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
    case 'records':
      return <RecordsScreen />
    case 'doctor':
      // The server refuses doctor routes to anyone who is not an approved doctor;
      // this check only keeps the screen from showing for the wrong account.
      return user?.role === 'doctor' ? <DoctorScreen /> : <InputScreen />
    default:
      return <InputScreen />
  }
}

function Router() {
  const { screen } = useApp()
  const { status, user } = useAuth()

  // The landing page is a standalone marketing homepage with no app chrome,
  // and it is the ONLY screen visible without signing in.
  if (screen === 'landing') {
    return <LandingScreen />
  }

  if (status === 'loading') {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-background">
        <Loader2 className="size-6 animate-spin text-muted-foreground" aria-label="Loading" />
      </div>
    )
  }

  if (status !== 'authenticated' || !user) {
    return <AuthScreen />
  }

  if (user.role === 'admin') {
    return <AdminNoticeScreen />
  }

  // A doctor can use the app only while their PMDC approval is active. This
  // screen is a courtesy -- the SERVER refuses every doctor request (403)
  // unless the approval is valid, whatever the screen shows.
  if (user.role === 'doctor' && user.status !== 'verified') {
    return <DoctorNotActiveScreen />
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
      <AuthProvider>
        <AppProvider>
          <Router />
        </AppProvider>
      </AuthProvider>
    </ToastProvider>
  )
}
