import { useEffect, useRef, useState } from 'react'
import { ExternalLink, RefreshCw, ShieldAlert } from 'lucide-react'
import { serviceIcon } from './icons'
import { ServiceStatusBadge, buttonClass, ghostButtonClass } from './ui'

// Um navegador que recusa o quadro (X-Frame-Options do serviço) não avisa a
// página: só nunca dispara o load. Depois deste tempo o painel assume bloqueio
// e oferece a nova aba, sem tirar o quadro da tela.
const LOAD_TIMEOUT_MS = 8000

export default function ServiceFrame({ service, health }) {
  const [loaded, setLoaded] = useState(false)
  const [slow, setSlow] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  const frameRef = useRef(null)

  useEffect(() => {
    setLoaded(false)
    setSlow(false)
    const timer = setTimeout(() => setSlow(true), LOAD_TIMEOUT_MS)
    return () => clearTimeout(timer)
  }, [service.slug, reloadKey])

  const Icon = serviceIcon(service.icon)

  const header = (
    <header className="flex flex-wrap items-center gap-3 mb-3">
      <div className="flex items-center gap-2 min-w-0">
        <span className="p-2 rounded-lg bg-blue-600/20 text-blue-400">
          <Icon size={18} />
        </span>
        <div className="min-w-0">
          <h1 className="text-lg font-bold text-white truncate">{service.name}</h1>
          <p className="text-xs text-slate-500 truncate">{service.description}</p>
        </div>
      </div>
      <div className="flex items-center gap-2 ml-auto">
        {health && <ServiceStatusBadge status={health.status} latency={health.latency_ms} />}
        {service.embeddable && service.url && (
          <button
            onClick={() => setReloadKey((key) => key + 1)}
            className={ghostButtonClass}
            title="Recarregar"
          >
            <RefreshCw size={15} />
          </button>
        )}
        {service.url && (
          <a href={service.url} target="_blank" rel="noreferrer" className={ghostButtonClass}>
            <ExternalLink size={15} />
            Nova aba
          </a>
        )}
      </div>
    </header>
  )

  if (!service.url) {
    return (
      <div className="space-y-3">
        {header}
        <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-6 text-sm text-slate-400">
          Este serviço não tem interface web: ele é usado pelo aplicativo cliente. O painel apenas
          monitora a disponibilidade dele.
        </div>
      </div>
    )
  }

  if (!service.embeddable) {
    return (
      <div className="space-y-3">
        {header}
        <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-8 text-center">
          <ShieldAlert size={28} className="mx-auto mb-3 text-amber-400" />
          <p className="text-sm text-slate-300">
            {service.name} não permite ser exibido dentro de outra página (política do próprio
            serviço). Abra em uma aba dedicada — a sessão é a mesma.
          </p>
          <a
            href={service.url}
            target="_blank"
            rel="noreferrer"
            className={`${buttonClass} mt-5`}
          >
            <ExternalLink size={16} />
            Abrir {service.name}
          </a>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {header}
      {slow && !loaded && (
        <div className="bg-amber-900/20 border border-amber-900 rounded-lg p-3 text-xs text-amber-300 flex items-center gap-2">
          <ShieldAlert size={15} />
          <span>
            {service.name} está demorando a abrir aqui dentro. Se a área continuar vazia, o serviço
            recusou o quadro — use “Nova aba”.
          </span>
        </div>
      )}
      <div className="relative bg-slate-900 border border-slate-800 rounded-xl overflow-hidden h-[calc(100vh-13rem)] min-h-[420px]">
        {!loaded && (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-slate-500">
            Abrindo {service.name}…
          </div>
        )}
        <iframe
          key={reloadKey}
          ref={frameRef}
          src={service.url}
          title={service.name}
          onLoad={() => setLoaded(true)}
          className="w-full h-full bg-white"
          allow="clipboard-read; clipboard-write; fullscreen; microphone; camera; display-capture"
        />
      </div>
    </div>
  )
}
