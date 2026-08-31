import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Search, X } from 'lucide-react'
import { apiMessage, ticketsApi } from '../api/client'
import {
  Card,
  EmptyState,
  ErrorState,
  Field,
  Loading,
  PriorityLabel,
  TicketStatusBadge,
  buttonClass,
  formatDateTime,
  ghostButtonClass,
  inputClass,
  isOverdue,
} from '../components/ui'

const STATUS_FILTERS = [
  { value: 'notold', label: 'Abertos' },
  { value: '1', label: 'Novos' },
  { value: '2', label: 'Em atendimento' },
  { value: '4', label: 'Pendentes' },
  { value: 'old', label: 'Encerrados' },
  { value: 'all', label: 'Todos' },
]

const URGENCIES = [
  { value: 5, label: 'Muito alta' },
  { value: 4, label: 'Alta' },
  { value: 3, label: 'Média' },
  { value: 2, label: 'Baixa' },
  { value: 1, label: 'Muito baixa' },
]

function NewTicketDialog({ onClose }) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState({ title: '', content: '', urgency: 3, type: 1 })
  const [error, setError] = useState('')

  const mutation = useMutation({
    mutationFn: () => ticketsApi.create(form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tickets'] })
      queryClient.invalidateQueries({ queryKey: ['summary'] })
      onClose()
    },
    onError: (err) => setError(apiMessage(err, 'Não foi possível abrir o chamado')),
  })

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4">
      <div className="w-full max-w-lg bg-slate-900 border border-slate-700 rounded-xl p-5">
        <header className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold text-white">Novo chamado</h2>
          <button onClick={onClose} className="text-slate-500 hover:text-white" aria-label="Fechar">
            <X size={18} />
          </button>
        </header>

        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault()
            setError('')
            mutation.mutate()
          }}
        >
          <Field label="Título">
            <input
              className={inputClass}
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              maxLength={255}
              autoFocus
            />
          </Field>

          <Field label="Descrição">
            <textarea
              className={`${inputClass} h-32 resize-y`}
              value={form.content}
              onChange={(e) => setForm({ ...form, content: e.target.value })}
            />
          </Field>

          <div className="grid grid-cols-2 gap-4">
            <Field label="Urgência">
              <select
                className={inputClass}
                value={form.urgency}
                onChange={(e) => setForm({ ...form, urgency: Number(e.target.value) })}
              >
                {URGENCIES.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Tipo">
              <select
                className={inputClass}
                value={form.type}
                onChange={(e) => setForm({ ...form, type: Number(e.target.value) })}
              >
                <option value={1}>Incidente</option>
                <option value={2}>Requisição</option>
              </select>
            </Field>
          </div>

          {error && (
            <div className="bg-red-900/30 border border-red-800 rounded-lg p-3 text-sm text-red-400">
              {error}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onClose} className={ghostButtonClass}>
              Cancelar
            </button>
            <button
              type="submit"
              className={buttonClass}
              disabled={mutation.isPending || !form.title.trim() || !form.content.trim()}
            >
              {mutation.isPending ? 'Abrindo…' : 'Abrir chamado'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function TicketsPage() {
  const [status, setStatus] = useState('notold')
  const [term, setTerm] = useState('')
  const [search, setSearch] = useState('')
  const [creating, setCreating] = useState(false)

  const { data: tickets = [], isLoading, error, refetch } = useQuery({
    queryKey: ['tickets', status, search],
    queryFn: () => ticketsApi.list({ status, search, limit: 100 }),
    refetchInterval: 60000,
  })

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Chamados</h1>
          <p className="text-sm text-slate-500">Fila do GLPI, sem sair do painel.</p>
        </div>
        <button onClick={() => setCreating(true)} className={buttonClass}>
          <Plus size={16} />
          Novo chamado
        </button>
      </header>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1">
          {STATUS_FILTERS.map((filter) => (
            <button
              key={filter.value}
              onClick={() => setStatus(filter.value)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                status === filter.value
                  ? 'bg-blue-600/20 text-blue-400'
                  : 'text-slate-400 hover:bg-slate-800'
              }`}
            >
              {filter.label}
            </button>
          ))}
        </div>
        <form
          className="relative ml-auto"
          onSubmit={(event) => {
            event.preventDefault()
            setSearch(term.trim())
          }}
        >
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            placeholder="Buscar pelo título…"
            className={`${inputClass} pl-9 w-64`}
          />
        </form>
      </div>

      {isLoading && <Loading />}
      {error && <ErrorState message={apiMessage(error)} onRetry={refetch} />}

      {!isLoading && !error && (
        <Card>
          {tickets.length === 0 ? (
            <EmptyState
              message="Nenhum chamado neste filtro"
              hint="Troque o filtro ou abra um chamado novo."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wide text-slate-500">
                    <th className="py-2 pr-3 font-medium">#</th>
                    <th className="py-2 pr-3 font-medium">Título</th>
                    <th className="py-2 pr-3 font-medium hidden lg:table-cell">Cliente</th>
                    <th className="py-2 pr-3 font-medium hidden md:table-cell">Técnico</th>
                    <th className="py-2 pr-3 font-medium hidden xl:table-cell">Aberto em</th>
                    <th className="py-2 pr-3 font-medium">Prazo</th>
                    <th className="py-2 pr-3 font-medium">Prioridade</th>
                    <th className="py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-700/60">
                  {tickets.map((ticket) => (
                    <tr key={ticket.id} className="hover:bg-slate-800/40">
                      <td className="py-2.5 pr-3 text-slate-600">{ticket.id}</td>
                      <td className="py-2.5 pr-3 max-w-md">
                        <Link
                          to={`/chamados/${ticket.id}`}
                          className="text-slate-200 hover:text-blue-400 block truncate"
                        >
                          {ticket.title || '(sem título)'}
                        </Link>
                      </td>
                      <td className="py-2.5 pr-3 text-slate-400 hidden lg:table-cell truncate max-w-[12rem]">
                        {ticket.entity || '—'}
                      </td>
                      <td className="py-2.5 pr-3 text-slate-400 hidden md:table-cell truncate max-w-[10rem]">
                        {ticket.technician || '—'}
                      </td>
                      <td className="py-2.5 pr-3 text-slate-500 hidden xl:table-cell whitespace-nowrap">
                        {formatDateTime(ticket.opened_at)}
                      </td>
                      <td
                        className={`py-2.5 pr-3 whitespace-nowrap ${
                          isOverdue(ticket.due_at) && ticket.status < 5
                            ? 'text-red-400'
                            : 'text-slate-500'
                        }`}
                      >
                        {formatDateTime(ticket.due_at)}
                      </td>
                      <td className="py-2.5 pr-3">
                        <PriorityLabel priority={ticket.priority} label={ticket.priority_label} />
                      </td>
                      <td className="py-2.5">
                        <TicketStatusBadge status={ticket.status} label={ticket.status_label} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {creating && <NewTicketDialog onClose={() => setCreating(false)} />}
    </div>
  )
}
