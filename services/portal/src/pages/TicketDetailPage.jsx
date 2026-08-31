import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, CheckCircle2, MessageSquarePlus } from 'lucide-react'
import { apiMessage, ticketsApi } from '../api/client'
import {
  Card,
  ErrorState,
  Loading,
  PriorityLabel,
  TicketStatusBadge,
  buttonClass,
  formatDateTime,
  ghostButtonClass,
  inputClass,
  isOverdue,
} from '../components/ui'

function Detail({ label, children }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className="text-sm text-slate-200 mt-0.5">{children || '—'}</p>
    </div>
  )
}

export default function TicketDetailPage() {
  const { ticketId } = useParams()
  const queryClient = useQueryClient()
  const [followup, setFollowup] = useState('')
  const [isPrivate, setIsPrivate] = useState(false)
  const [solution, setSolution] = useState('')
  const [solving, setSolving] = useState(false)
  const [error, setError] = useState('')

  const { data: ticket, isLoading, error: loadError, refetch } = useQuery({
    queryKey: ['ticket', ticketId],
    queryFn: () => ticketsApi.get(ticketId),
  })

  const invalidate = (data) => {
    queryClient.setQueryData(['ticket', ticketId], data)
    queryClient.invalidateQueries({ queryKey: ['tickets'] })
    queryClient.invalidateQueries({ queryKey: ['summary'] })
  }

  const followupMutation = useMutation({
    mutationFn: () => ticketsApi.addFollowup(ticketId, { content: followup, is_private: isPrivate }),
    onSuccess: (data) => {
      invalidate(data)
      setFollowup('')
      setIsPrivate(false)
    },
    onError: (err) => setError(apiMessage(err, 'Não foi possível registrar o acompanhamento')),
  })

  const solutionMutation = useMutation({
    mutationFn: () => ticketsApi.solve(ticketId, { content: solution }),
    onSuccess: (data) => {
      invalidate(data)
      setSolution('')
      setSolving(false)
    },
    onError: (err) => setError(apiMessage(err, 'Não foi possível registrar a solução')),
  })

  if (isLoading) return <Loading />
  if (loadError) return <ErrorState message={apiMessage(loadError)} onRetry={refetch} />

  const closed = ticket.status >= 5

  return (
    <div className="space-y-5 max-w-4xl">
      <Link
        to="/chamados"
        className="inline-flex items-center gap-1 text-sm text-slate-400 hover:text-white"
      >
        <ArrowLeft size={15} />
        Voltar para os chamados
      </Link>

      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs text-slate-600">Chamado #{ticket.id}</p>
          <h1 className="text-2xl font-bold text-white">{ticket.title || '(sem título)'}</h1>
        </div>
        <div className="flex items-center gap-2">
          <PriorityLabel priority={ticket.priority} label={ticket.priority_label} />
          <TicketStatusBadge status={ticket.status} label={ticket.status_label} />
        </div>
      </header>

      <Card>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Detail label="Cliente">{ticket.entity}</Detail>
          <Detail label="Tipo">{ticket.type_label}</Detail>
          <Detail label="Aberto em">{formatDateTime(ticket.opened_at)}</Detail>
          <Detail label="Prazo">
            <span className={isOverdue(ticket.due_at) && !closed ? 'text-red-400' : undefined}>
              {formatDateTime(ticket.due_at)}
            </span>
          </Detail>
        </div>
        <p className="mt-5 text-sm text-slate-300 whitespace-pre-wrap">{ticket.content || '—'}</p>
      </Card>

      <Card title={`Acompanhamentos (${ticket.followups?.length || 0})`}>
        <div className="space-y-3">
          {(ticket.followups || []).length === 0 && (
            <p className="text-sm text-slate-500">Nenhum acompanhamento registrado.</p>
          )}
          {(ticket.followups || []).map((item) => (
            <article key={item.id} className="border-l-2 border-slate-700 pl-3">
              <p className="text-[11px] text-slate-500">
                {item.author || 'Sistema'} · {formatDateTime(item.created_at)}
                {item.is_private && <span className="ml-2 text-amber-500">privado</span>}
              </p>
              <p className="text-sm text-slate-300 whitespace-pre-wrap mt-0.5">{item.content}</p>
            </article>
          ))}
        </div>
      </Card>

      {error && <ErrorState message={error} />}

      {!closed && (
        <Card title="Responder">
          <textarea
            className={`${inputClass} h-24 resize-y`}
            placeholder="O que foi feito ou o que falta…"
            value={followup}
            onChange={(e) => setFollowup(e.target.value)}
          />
          <div className="flex flex-wrap items-center gap-3 mt-3">
            <label className="flex items-center gap-2 text-xs text-slate-400">
              <input
                type="checkbox"
                checked={isPrivate}
                onChange={(e) => setIsPrivate(e.target.checked)}
                className="rounded border-slate-600 bg-slate-900"
              />
              Nota interna (não visível ao cliente)
            </label>
            <div className="ml-auto flex gap-2">
              <button
                onClick={() => setSolving((value) => !value)}
                className={ghostButtonClass}
                type="button"
              >
                <CheckCircle2 size={15} />
                Solucionar
              </button>
              <button
                onClick={() => {
                  setError('')
                  followupMutation.mutate()
                }}
                disabled={followupMutation.isPending || !followup.trim()}
                className={buttonClass}
                type="button"
              >
                <MessageSquarePlus size={15} />
                {followupMutation.isPending ? 'Enviando…' : 'Registrar'}
              </button>
            </div>
          </div>

          {solving && (
            <div className="mt-4 pt-4 border-t border-slate-700 space-y-3">
              <textarea
                className={`${inputClass} h-24 resize-y`}
                placeholder="Descreva a solução aplicada…"
                value={solution}
                onChange={(e) => setSolution(e.target.value)}
              />
              <div className="flex justify-end gap-2">
                <button onClick={() => setSolving(false)} className={ghostButtonClass} type="button">
                  Cancelar
                </button>
                <button
                  onClick={() => {
                    setError('')
                    solutionMutation.mutate()
                  }}
                  disabled={solutionMutation.isPending || !solution.trim()}
                  className={buttonClass}
                  type="button"
                >
                  {solutionMutation.isPending ? 'Registrando…' : 'Marcar como solucionado'}
                </button>
              </div>
            </div>
          )}
        </Card>
      )}
    </div>
  )
}
