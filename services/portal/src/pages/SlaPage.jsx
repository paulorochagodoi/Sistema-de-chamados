import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Calculator, Clock } from 'lucide-react'
import { apiMessage, slaApi } from '../api/client'
import {
  Card,
  ErrorState,
  Field,
  buttonClass,
  formatDateTime,
  inputClass,
} from '../components/ui'

const WEEKDAYS = [
  { value: 0, label: 'Seg' },
  { value: 1, label: 'Ter' },
  { value: 2, label: 'Qua' },
  { value: 3, label: 'Qui' },
  { value: 4, label: 'Sex' },
  { value: 5, label: 'Sáb' },
  { value: 6, label: 'Dom' },
]

function nowLocalInput() {
  const now = new Date()
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset())
  return now.toISOString().slice(0, 16)
}

export default function SlaPage() {
  const [form, setForm] = useState({
    opened_at: nowLocalInput(),
    response_minutes: 30,
    resolution_minutes: 240,
    start: '08:00',
    end: '18:00',
    workdays: [0, 1, 2, 3, 4],
    around_the_clock: false,
  })

  const mutation = useMutation({
    mutationFn: () =>
      slaApi.deadline({
        opened_at: form.opened_at,
        response_minutes: Number(form.response_minutes),
        resolution_minutes: Number(form.resolution_minutes),
        business_hours: {
          start: form.start,
          end: form.end,
          workdays: form.workdays,
          around_the_clock: form.around_the_clock,
        },
      }),
  })

  const toggleDay = (day) =>
    setForm((state) => ({
      ...state,
      workdays: state.workdays.includes(day)
        ? state.workdays.filter((value) => value !== day)
        : [...state.workdays, day].sort(),
    }))

  return (
    <div className="space-y-5 max-w-3xl">
      <header>
        <h1 className="text-2xl font-bold text-white">Prazos de SLA</h1>
        <p className="text-sm text-slate-500">
          Mesmo cálculo que o bridge aplica no escalonamento automático: a janela de atendimento do
          contrato é respeitada, não é hora corrida.
        </p>
      </header>

      <Card title="Contrato" icon={Calculator}>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault()
            mutation.mutate()
          }}
        >
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Field label="Abertura do chamado">
              <input
                type="datetime-local"
                className={inputClass}
                value={form.opened_at}
                onChange={(e) => setForm({ ...form, opened_at: e.target.value })}
              />
            </Field>
            <Field label="Resposta (min)">
              <input
                type="number"
                min="1"
                className={inputClass}
                value={form.response_minutes}
                onChange={(e) => setForm({ ...form, response_minutes: e.target.value })}
              />
            </Field>
            <Field label="Resolução (min)">
              <input
                type="number"
                min="1"
                className={inputClass}
                value={form.resolution_minutes}
                onChange={(e) => setForm({ ...form, resolution_minutes: e.target.value })}
              />
            </Field>
          </div>

          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={form.around_the_clock}
              onChange={(e) => setForm({ ...form, around_the_clock: e.target.checked })}
              className="rounded border-slate-600 bg-slate-900"
            />
            Contrato 24x7 (ignora janela e feriados)
          </label>

          {!form.around_the_clock && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <Field label="Início do expediente">
                <input
                  type="time"
                  className={inputClass}
                  value={form.start}
                  onChange={(e) => setForm({ ...form, start: e.target.value })}
                />
              </Field>
              <Field label="Fim do expediente">
                <input
                  type="time"
                  className={inputClass}
                  value={form.end}
                  onChange={(e) => setForm({ ...form, end: e.target.value })}
                />
              </Field>
              <Field label="Dias úteis">
                <div className="flex flex-wrap gap-1">
                  {WEEKDAYS.map((day) => (
                    <button
                      key={day.value}
                      type="button"
                      onClick={() => toggleDay(day.value)}
                      className={`px-2 py-1.5 rounded-lg text-xs font-medium ${
                        form.workdays.includes(day.value)
                          ? 'bg-blue-600/20 text-blue-400'
                          : 'text-slate-500 hover:bg-slate-800'
                      }`}
                    >
                      {day.label}
                    </button>
                  ))}
                </div>
              </Field>
            </div>
          )}

          <button type="submit" className={buttonClass} disabled={mutation.isPending}>
            <Clock size={16} />
            {mutation.isPending ? 'Calculando…' : 'Calcular prazos'}
          </button>
        </form>
      </Card>

      {mutation.isError && <ErrorState message={apiMessage(mutation.error)} />}

      {mutation.data && (
        <Card title="Prazos">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="bg-slate-900/60 border border-slate-700 rounded-lg p-4">
              <p className="text-[11px] uppercase tracking-wide text-slate-500">Responder até</p>
              <p className="text-lg font-bold text-white mt-1">
                {formatDateTime(mutation.data.response_due_at.replace('T', ' '))}
              </p>
              <p className="text-xs text-slate-500 mt-1">
                {mutation.data.business_minutes_to_response} min úteis
              </p>
            </div>
            <div className="bg-slate-900/60 border border-slate-700 rounded-lg p-4">
              <p className="text-[11px] uppercase tracking-wide text-slate-500">Resolver até</p>
              <p className="text-lg font-bold text-white mt-1">
                {formatDateTime(mutation.data.resolution_due_at.replace('T', ' '))}
              </p>
              <p className="text-xs text-slate-500 mt-1">
                {mutation.data.business_minutes_to_resolution} min úteis
              </p>
            </div>
          </div>
        </Card>
      )}
    </div>
  )
}
