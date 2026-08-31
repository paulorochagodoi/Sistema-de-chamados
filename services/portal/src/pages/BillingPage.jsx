import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Plus, Receipt, Trash2 } from 'lucide-react'
import { apiMessage, billingApi } from '../api/client'
import {
  Card,
  ErrorState,
  Field,
  buttonClass,
  ghostButtonClass,
  inputClass,
} from '../components/ui'

const BILLING_MODELS = [
  { value: 'hourly', label: 'Por hora apontada' },
  { value: 'per_ticket', label: 'Por chamado encerrado' },
  { value: 'per_asset', label: 'Por ativo monitorado' },
  { value: 'fixed', label: 'Recorrência fixa' },
  { value: 'fixed_plus_hourly', label: 'Fixo + excedente por hora' },
]

const firstDayOfMonth = () => new Date().toISOString().slice(0, 8) + '01'
const today = () => new Date().toISOString().slice(0, 10)

export default function BillingPage() {
  const [contract, setContract] = useState({
    id: 'CT-001',
    client: '',
    billing_model: 'hourly',
    hourly_rate: '150.00',
    fixed_amount: '0',
    per_ticket_rate: '0',
    per_asset_rate: '0',
    included_hours: '0',
    minimum_billable_minutes: 0,
    rounding_increment_minutes: 15,
    discount_percent: '0',
    tax_percent: '0',
  })
  const [period, setPeriod] = useState({ start: firstDayOfMonth(), end: today() })
  const [entries, setEntries] = useState([{ ticket_id: '', minutes: 60, billable: true }])
  const [counts, setCounts] = useState({ closed_tickets: 0, monitored_assets: 0 })

  const mutation = useMutation({
    mutationFn: () =>
      billingApi.preview({
        contract,
        period_start: period.start,
        period_end: period.end,
        time_entries: entries
          .filter((entry) => Number(entry.minutes) > 0)
          .map((entry) => ({
            ticket_id: Number(entry.ticket_id) || 0,
            minutes: Number(entry.minutes),
            billable: entry.billable,
          })),
        closed_tickets: Number(counts.closed_tickets) || 0,
        monitored_assets: Number(counts.monitored_assets) || 0,
      }),
  })

  const invoice = mutation.data

  return (
    <div className="space-y-5 max-w-4xl">
      <header>
        <h1 className="text-2xl font-bold text-white">Faturamento</h1>
        <p className="text-sm text-slate-500">
          Prévia da fatura a partir dos apontamentos — o mesmo cálculo que o n8n envia ao ERP, aqui
          para conferência antes de emitir.
        </p>
      </header>

      <Card title="Contrato" icon={Receipt}>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Field label="Identificador">
            <input
              className={inputClass}
              value={contract.id}
              onChange={(e) => setContract({ ...contract, id: e.target.value })}
            />
          </Field>
          <Field label="Cliente">
            <input
              className={inputClass}
              value={contract.client}
              onChange={(e) => setContract({ ...contract, client: e.target.value })}
              placeholder="Razão social"
            />
          </Field>
          <Field label="Modelo">
            <select
              className={inputClass}
              value={contract.billing_model}
              onChange={(e) => setContract({ ...contract, billing_model: e.target.value })}
            >
              {BILLING_MODELS.map((model) => (
                <option key={model.value} value={model.value}>
                  {model.label}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
          <Field label="Valor fixo">
            <input
              className={inputClass}
              value={contract.fixed_amount}
              onChange={(e) => setContract({ ...contract, fixed_amount: e.target.value })}
            />
          </Field>
          <Field label="Valor/hora">
            <input
              className={inputClass}
              value={contract.hourly_rate}
              onChange={(e) => setContract({ ...contract, hourly_rate: e.target.value })}
            />
          </Field>
          <Field label="Horas incluídas">
            <input
              className={inputClass}
              value={contract.included_hours}
              onChange={(e) => setContract({ ...contract, included_hours: e.target.value })}
            />
          </Field>
          <Field label="Arredondamento (min)" hint="Múltiplo cobrado por apontamento">
            <input
              type="number"
              min="1"
              className={inputClass}
              value={contract.rounding_increment_minutes}
              onChange={(e) =>
                setContract({ ...contract, rounding_increment_minutes: Number(e.target.value) })
              }
            />
          </Field>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
          <Field label="Início do período">
            <input
              type="date"
              className={inputClass}
              value={period.start}
              onChange={(e) => setPeriod({ ...period, start: e.target.value })}
            />
          </Field>
          <Field label="Fim do período">
            <input
              type="date"
              className={inputClass}
              value={period.end}
              onChange={(e) => setPeriod({ ...period, end: e.target.value })}
            />
          </Field>
          <Field label="Chamados encerrados">
            <input
              type="number"
              min="0"
              className={inputClass}
              value={counts.closed_tickets}
              onChange={(e) => setCounts({ ...counts, closed_tickets: e.target.value })}
            />
          </Field>
          <Field label="Ativos monitorados">
            <input
              type="number"
              min="0"
              className={inputClass}
              value={counts.monitored_assets}
              onChange={(e) => setCounts({ ...counts, monitored_assets: e.target.value })}
            />
          </Field>
        </div>
      </Card>

      <Card
        title="Apontamentos"
        action={
          <button
            onClick={() => setEntries([...entries, { ticket_id: '', minutes: 60, billable: true }])}
            className={ghostButtonClass}
            type="button"
          >
            <Plus size={15} />
            Linha
          </button>
        }
      >
        <div className="space-y-2">
          {entries.map((entry, index) => (
            <div key={index} className="flex flex-wrap items-center gap-2">
              <input
                className={`${inputClass} w-28`}
                placeholder="Chamado"
                value={entry.ticket_id}
                onChange={(e) =>
                  setEntries(
                    entries.map((item, position) =>
                      position === index ? { ...item, ticket_id: e.target.value } : item,
                    ),
                  )
                }
              />
              <input
                type="number"
                min="0"
                className={`${inputClass} w-28`}
                value={entry.minutes}
                onChange={(e) =>
                  setEntries(
                    entries.map((item, position) =>
                      position === index ? { ...item, minutes: e.target.value } : item,
                    ),
                  )
                }
              />
              <span className="text-xs text-slate-500">min</span>
              <label className="flex items-center gap-2 text-xs text-slate-400">
                <input
                  type="checkbox"
                  checked={entry.billable}
                  onChange={(e) =>
                    setEntries(
                      entries.map((item, position) =>
                        position === index ? { ...item, billable: e.target.checked } : item,
                      ),
                    )
                  }
                  className="rounded border-slate-600 bg-slate-900"
                />
                Faturável
              </label>
              <button
                onClick={() => setEntries(entries.filter((_, position) => position !== index))}
                className="ml-auto text-slate-500 hover:text-red-400"
                type="button"
                aria-label="Remover linha"
              >
                <Trash2 size={15} />
              </button>
            </div>
          ))}
        </div>

        <button
          onClick={() => mutation.mutate()}
          className={`${buttonClass} mt-4`}
          disabled={mutation.isPending}
          type="button"
        >
          <Receipt size={16} />
          {mutation.isPending ? 'Calculando…' : 'Calcular prévia'}
        </button>
      </Card>

      {mutation.isError && <ErrorState message={apiMessage(mutation.error)} />}

      {invoice && (
        <Card title={`Fatura — ${invoice.client || invoice.contract_id}`}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wide text-slate-500">
                  <th className="py-2 pr-3 font-medium">Linha</th>
                  <th className="py-2 pr-3 font-medium text-right">Qtd.</th>
                  <th className="py-2 pr-3 font-medium text-right">Unitário</th>
                  <th className="py-2 font-medium text-right">Valor</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/60">
                {invoice.lines.map((line, index) => (
                  <tr key={index}>
                    <td className="py-2 pr-3 text-slate-300">{line.description}</td>
                    <td className="py-2 pr-3 text-right text-slate-400">{line.quantity}</td>
                    <td className="py-2 pr-3 text-right text-slate-400">{line.unit_price}</td>
                    <td className="py-2 text-right text-slate-200">{line.amount}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-4 pt-4 border-t border-slate-700 flex flex-wrap gap-6 justify-end text-sm">
            <span className="text-slate-400">
              Subtotal <span className="text-slate-200 ml-1">{invoice.subtotal}</span>
            </span>
            <span className="text-slate-400">
              Descontos <span className="text-slate-200 ml-1">{invoice.discount}</span>
            </span>
            <span className="text-slate-400">
              Impostos <span className="text-slate-200 ml-1">{invoice.tax}</span>
            </span>
            <span className="text-white font-bold">
              Total {invoice.currency} {invoice.total}
            </span>
          </div>
          <p className="text-[11px] text-slate-600 mt-2 text-right">
            {invoice.billable_minutes} min faturáveis · {invoice.non_billable_minutes} min não
            faturáveis
          </p>
        </Card>
      )}
    </div>
  )
}
