import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock,
  Server,
  Ticket,
  UserX,
} from 'lucide-react'
import { ticketsApi } from '../api/client'
import { serviceIcon } from '../components/icons'
import {
  Card,
  ErrorState,
  Loading,
  MetricCard,
  ServiceStatusBadge,
  TicketStatusBadge,
  formatDateTime,
  isOverdue,
} from '../components/ui'

function Bar({ label, value, total, tone = 'bg-blue-500' }) {
  const pct = total > 0 ? Math.round((value / total) * 100) : 0
  return (
    <div>
      <div className="flex items-center justify-between text-xs mb-1">
        <span className="text-slate-400">{label}</span>
        <span className="text-slate-300 font-medium">{value}</span>
      </div>
      <div className="h-1.5 bg-slate-700/60 rounded-full overflow-hidden">
        <div className={`h-full ${tone} rounded-full`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export default function DashboardPage({ services = [], health = {} }) {
  const {
    data: summary,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ['summary'],
    queryFn: ticketsApi.summary,
    refetchInterval: 60000,
  })

  if (isLoading) return <Loading />
  if (error) {
    return (
      <ErrorState
        message={`Não foi possível ler os chamados: ${error.response?.data?.detail || error.message}`}
        onRetry={refetch}
      />
    )
  }

  const offline = services.filter((service) => health[service.slug]?.status === 'offline')
  const totalOpen = summary.open || 0

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Painel</h1>
          <p className="text-sm text-slate-500">
            Chamados abertos, prazos e saúde da stack — tudo em uma tela.
          </p>
        </div>
        <Link
          to="/chamados"
          className="text-sm text-blue-400 hover:text-blue-300 inline-flex items-center gap-1"
        >
          Ver todos os chamados <ArrowRight size={14} />
        </Link>
      </header>

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <MetricCard icon={Ticket} value={totalOpen} label="Chamados abertos" tone="blue" />
        <MetricCard
          icon={AlertTriangle}
          value={summary.overdue || 0}
          label="Com prazo estourado"
          tone={summary.overdue ? 'red' : 'slate'}
        />
        <MetricCard
          icon={Clock}
          value={summary.at_risk || 0}
          label="Prazo a vencer"
          tone={summary.at_risk ? 'amber' : 'slate'}
        />
        <MetricCard
          icon={UserX}
          value={summary.unassigned || 0}
          label="Sem técnico"
          tone={summary.unassigned ? 'amber' : 'slate'}
        />
        <MetricCard
          icon={offline.length ? Server : CheckCircle2}
          value={`${services.length - offline.length}/${services.length}`}
          label="Serviços online"
          tone={offline.length ? 'red' : 'green'}
        />
      </div>

      {offline.length > 0 && (
        <div className="bg-red-900/20 border border-red-900 rounded-xl p-4">
          <p className="text-sm text-red-300 font-medium mb-2 flex items-center gap-2">
            <AlertTriangle size={16} />
            {offline.length} serviço(s) sem resposta
          </p>
          <div className="flex flex-wrap gap-2">
            {offline.map((service) => (
              <Link
                key={service.slug}
                to={`/servicos/${service.slug}`}
                className="text-xs px-2 py-1 rounded-lg bg-red-900/40 text-red-200 hover:bg-red-900/60"
              >
                {service.name}
              </Link>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card title="Chamados por status" icon={Ticket}>
          <div className="space-y-3">
            {Object.entries(summary.by_status || {}).length === 0 && (
              <p className="text-sm text-slate-500">Nenhum chamado aberto.</p>
            )}
            {Object.entries(summary.by_status || {}).map(([label, value]) => (
              <Bar key={label} label={label} value={value} total={summary.total || 0} />
            ))}
          </div>
        </Card>

        <Card title="Carga por técnico" icon={UserX}>
          <div className="space-y-3">
            {Object.entries(summary.by_technician || {}).length === 0 && (
              <p className="text-sm text-slate-500">Nada atribuído no momento.</p>
            )}
            {Object.entries(summary.by_technician || {})
              .slice(0, 6)
              .map(([label, value]) => (
                <Bar
                  key={label}
                  label={label}
                  value={value}
                  total={totalOpen}
                  tone={label === 'Não atribuído' ? 'bg-amber-500' : 'bg-blue-500'}
                />
              ))}
          </div>
        </Card>
      </div>

      <Card title="Últimos chamados" icon={Ticket}>
        <div className="divide-y divide-slate-700/60">
          {(summary.recent || []).length === 0 && (
            <p className="text-sm text-slate-500 py-2">Nenhum chamado aberto.</p>
          )}
          {(summary.recent || []).map((ticket) => (
            <Link
              key={ticket.id}
              to={`/chamados/${ticket.id}`}
              className="flex items-center gap-3 py-2.5 hover:bg-slate-800/40 -mx-2 px-2 rounded-lg"
            >
              <span className="text-xs text-slate-600 w-12 shrink-0">#{ticket.id}</span>
              <span className="flex-1 text-sm text-slate-200 truncate">{ticket.title}</span>
              {isOverdue(ticket.due_at) && (
                <span className="text-[11px] text-red-400 hidden sm:inline">prazo vencido</span>
              )}
              <span className="text-xs text-slate-500 hidden md:inline">
                {formatDateTime(ticket.opened_at)}
              </span>
              <TicketStatusBadge status={ticket.status} label={ticket.status_label} />
            </Link>
          ))}
        </div>
      </Card>

      <Card title="Serviços da stack" icon={Server}>
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
          {services.map((service) => {
            const Icon = serviceIcon(service.icon)
            const state = health[service.slug]
            return (
              <Link
                key={service.slug}
                to={`/servicos/${service.slug}`}
                className="flex items-center gap-3 p-3 rounded-lg border border-slate-700 hover:border-blue-600/60 hover:bg-slate-800/40 transition-all"
              >
                <span className="p-2 rounded-lg bg-slate-700/40 text-slate-300">
                  <Icon size={16} />
                </span>
                <span className="flex-1 min-w-0">
                  <span className="block text-sm text-white truncate">{service.name}</span>
                  <span className="block text-[11px] text-slate-500 truncate">
                    {service.description}
                  </span>
                </span>
                <ServiceStatusBadge status={state?.status} latency={state?.latency_ms} />
              </Link>
            )
          })}
        </div>
      </Card>
    </div>
  )
}
