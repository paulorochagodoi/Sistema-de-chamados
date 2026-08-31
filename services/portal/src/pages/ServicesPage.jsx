import { Link } from 'react-router-dom'
import { ExternalLink } from 'lucide-react'
import { serviceIcon } from '../components/icons'
import { Card, EmptyState, ServiceStatusBadge } from '../components/ui'

const CATEGORY_LABELS = {
  itsm: 'Núcleo ITSM',
  operacao: 'Operação',
  plataforma: 'Plataforma',
}

export default function ServicesPage({ services = [], health = {} }) {
  const grouped = services.reduce((acc, service) => {
    ;(acc[service.category] ||= []).push(service)
    return acc
  }, {})

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-white">Status dos serviços</h1>
        <p className="text-sm text-slate-500">
          Checado por dentro da rede da stack, sem depender do certificado nem do DNS externo.
        </p>
      </header>

      {services.length === 0 && <EmptyState message="Nenhum serviço no catálogo" />}

      {Object.entries(CATEGORY_LABELS).map(([category, label]) => {
        const items = grouped[category] || []
        if (items.length === 0) return null
        return (
          <Card key={category} title={label}>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {items.map((service) => {
                const Icon = serviceIcon(service.icon)
                const state = health[service.slug]
                return (
                  <div
                    key={service.slug}
                    className="border border-slate-700 rounded-xl p-4 flex flex-col gap-3"
                  >
                    <div className="flex items-start gap-3">
                      <span className="p-2 rounded-lg bg-slate-700/40 text-slate-300">
                        <Icon size={18} />
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-white">{service.name}</p>
                        <p className="text-[11px] text-slate-500">{service.description}</p>
                      </div>
                    </div>

                    <div className="flex items-center justify-between gap-2">
                      <ServiceStatusBadge status={state?.status} latency={state?.latency_ms} />
                      <span className="text-[11px] text-slate-600">perfil {service.profile}</span>
                    </div>

                    {state?.detail && state.status !== 'online' && (
                      <p className="text-[11px] text-red-400 break-words">{state.detail}</p>
                    )}

                    <div className="flex items-center gap-2 mt-auto pt-1">
                      <Link
                        to={`/servicos/${service.slug}`}
                        className="text-xs text-blue-400 hover:text-blue-300"
                      >
                        Abrir no painel
                      </Link>
                      {service.url && (
                        <a
                          href={service.url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-xs text-slate-500 hover:text-slate-300 inline-flex items-center gap-1 ml-auto"
                        >
                          {service.url.replace('https://', '')}
                          <ExternalLink size={12} />
                        </a>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </Card>
        )
      })}
    </div>
  )
}
