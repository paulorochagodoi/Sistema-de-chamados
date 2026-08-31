import { useEffect, useState } from 'react'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import LoginPage from './components/LoginPage'
import Sidebar from './components/Sidebar'
import { Loading } from './components/ui'
import DashboardPage from './pages/DashboardPage'
import TicketsPage from './pages/TicketsPage'
import TicketDetailPage from './pages/TicketDetailPage'
import ServicesPage from './pages/ServicesPage'
import ServiceViewPage from './pages/ServiceViewPage'
import SlaPage from './pages/SlaPage'
import BillingPage from './pages/BillingPage'
import { authApi, servicesApi, TOKEN_KEY, USER_KEY } from './api/client'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
})

function Shell({ user, onLogout }) {
  const { data: services = [] } = useQuery({
    queryKey: ['services'],
    queryFn: servicesApi.list,
    staleTime: 5 * 60 * 1000,
  })

  // O status alimenta tanto a página de serviços quanto o ponto vermelho do menu.
  const { data: statusList = [] } = useQuery({
    queryKey: ['services-status'],
    queryFn: servicesApi.status,
    refetchInterval: 30000,
  })
  const health = Object.fromEntries(statusList.map((item) => [item.slug, item]))

  return (
    <div className="min-h-screen bg-slate-950">
      <Sidebar user={user} services={services} health={health} onLogout={onLogout} />
      <main className="lg:ml-64 p-4 lg:p-8 pt-16 lg:pt-8">
        <Routes>
          <Route path="/" element={<DashboardPage services={services} health={health} />} />
          <Route path="/chamados" element={<TicketsPage />} />
          <Route path="/chamados/:ticketId" element={<TicketDetailPage />} />
          <Route path="/sla" element={<SlaPage />} />
          <Route path="/faturamento" element={<BillingPage />} />
          <Route path="/servicos" element={<ServicesPage services={services} health={health} />} />
          <Route
            path="/servicos/:slug"
            element={<ServiceViewPage services={services} health={health} />}
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}

export default function App() {
  const [user, setUser] = useState(null)
  const [checking, setChecking] = useState(true)

  // Uma sessão pode vir de duas origens: o token guardado pelo login do painel
  // ou um proxy de SSO à frente dele (nesse caso /auth/me responde sem token).
  useEffect(() => {
    let active = true
    authApi
      .me()
      .then((data) => {
        if (!active) return
        setUser(data)
        localStorage.setItem(USER_KEY, JSON.stringify(data))
      })
      .catch(() => {
        if (!active) return
        localStorage.removeItem(TOKEN_KEY)
        localStorage.removeItem(USER_KEY)
        setUser(null)
      })
      .finally(() => active && setChecking(false))
    return () => {
      active = false
    }
  }, [])

  const handleLogout = () => {
    authApi.logout()
    setUser(null)
    queryClient.clear()
  }

  if (checking) {
    return (
      <div className="min-h-screen bg-slate-950">
        <Loading label="Abrindo o painel…" />
      </div>
    )
  }

  if (!user) {
    return <LoginPage onLogin={setUser} />
  }

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Shell user={user} onLogout={handleLogout} />
      </BrowserRouter>
    </QueryClientProvider>
  )
}
