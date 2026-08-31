import { AlertTriangle, Inbox, Loader2 } from 'lucide-react'

export function Card({ title, icon: Icon, action, className = '', children }) {
  return (
    <section className={`bg-slate-800/50 border border-slate-700 rounded-xl p-5 ${className}`}>
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 mb-4">
          <h2 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
            {Icon && <Icon size={16} className="text-blue-400" />}
            {title}
          </h2>
          {action}
        </header>
      )}
      {children}
    </section>
  )
}

export function MetricCard({ icon: Icon, value, label, tone = 'blue', hint }) {
  const tones = {
    blue: 'text-blue-400 bg-blue-600/20',
    green: 'text-green-400 bg-green-600/20',
    amber: 'text-amber-400 bg-amber-600/20',
    red: 'text-red-400 bg-red-600/20',
    slate: 'text-slate-400 bg-slate-600/20',
  }
  return (
    <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-4">
      <div className="flex items-center gap-3">
        <div className={`p-2 rounded-lg ${tones[tone]}`}>
          <Icon size={20} />
        </div>
        <div className="min-w-0">
          <p className="text-2xl font-bold text-white leading-tight">{value}</p>
          <p className="text-xs text-slate-400 truncate">{label}</p>
        </div>
      </div>
      {hint && <p className="text-[11px] text-slate-500 mt-2">{hint}</p>}
    </div>
  )
}

const statusTones = {
  online: 'bg-green-600/20 text-green-400 border-green-800',
  offline: 'bg-red-600/20 text-red-400 border-red-900',
  unknown: 'bg-slate-600/20 text-slate-400 border-slate-700',
}

export function ServiceStatusBadge({ status = 'unknown', latency }) {
  const labels = { online: 'Online', offline: 'Fora do ar', unknown: 'Sem resposta' }
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-[11px] font-medium ${statusTones[status] || statusTones.unknown}`}
    >
      <span className="w-1.5 h-1.5 rounded-full bg-current" />
      {labels[status] || labels.unknown}
      {status === 'online' && latency != null && <span className="opacity-70">{latency} ms</span>}
    </span>
  )
}

// Cores dos status do GLPI: 1 novo, 2 em atendimento, 3 planejado, 4 pendente,
// 5 solucionado, 6 fechado.
const ticketStatusTones = {
  1: 'bg-blue-600/20 text-blue-400',
  2: 'bg-amber-600/20 text-amber-400',
  3: 'bg-purple-600/20 text-purple-400',
  4: 'bg-orange-600/20 text-orange-400',
  5: 'bg-green-600/20 text-green-400',
  6: 'bg-slate-600/20 text-slate-400',
}

export function TicketStatusBadge({ status, label }) {
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded-md text-[11px] font-medium ${ticketStatusTones[status] || ticketStatusTones[6]}`}
    >
      {label || '—'}
    </span>
  )
}

const priorityTones = {
  5: 'text-red-400',
  4: 'text-orange-400',
  3: 'text-slate-300',
  2: 'text-slate-400',
  1: 'text-slate-500',
}

export function PriorityLabel({ priority, label }) {
  return (
    <span className={`text-xs font-medium ${priorityTones[priority] || 'text-slate-400'}`}>
      {label || '—'}
    </span>
  )
}

export function Loading({ label = 'Carregando…' }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-slate-400 text-sm">
      <Loader2 size={18} className="animate-spin" />
      {label}
    </div>
  )
}

export function ErrorState({ message, onRetry }) {
  return (
    <div className="bg-red-900/20 border border-red-900 rounded-xl p-4 text-sm text-red-300">
      <p className="flex items-center gap-2 font-medium">
        <AlertTriangle size={16} />
        {message}
      </p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-3 px-3 py-1.5 rounded-lg bg-red-900/40 hover:bg-red-900/60 text-xs font-medium"
        >
          Tentar de novo
        </button>
      )}
    </div>
  )
}

export function EmptyState({ message, hint }) {
  return (
    <div className="text-center py-14 text-slate-500">
      <Inbox size={28} className="mx-auto mb-3 opacity-60" />
      <p className="text-sm">{message}</p>
      {hint && <p className="text-xs mt-1 opacity-80">{hint}</p>}
    </div>
  )
}

export function Field({ label, hint, children }) {
  return (
    <label className="block">
      <span className="block text-sm font-medium text-slate-300 mb-1">{label}</span>
      {children}
      {hint && <span className="block text-[11px] text-slate-500 mt-1">{hint}</span>}
    </label>
  )
}

export const inputClass =
  'w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500'

export const buttonClass =
  'inline-flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:text-slate-500 rounded-lg text-sm font-medium text-white transition-all'

export const ghostButtonClass =
  'inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm font-medium text-slate-300 border border-slate-700 hover:bg-slate-800 transition-all'

/** Datas do GLPI chegam como "YYYY-MM-DD HH:MM:SS" (fuso da stack). */
export function formatDateTime(value) {
  if (!value) return '—'
  const parsed = new Date(value.replace(' ', 'T'))
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
}

export function isOverdue(value) {
  if (!value) return false
  const parsed = new Date(value.replace(' ', 'T'))
  return !Number.isNaN(parsed.getTime()) && parsed < new Date()
}
