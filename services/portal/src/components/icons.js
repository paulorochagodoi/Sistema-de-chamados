import {
  Activity,
  BarChart3,
  Box,
  Cast,
  Database,
  KeyRound,
  MessagesSquare,
  Monitor,
  Plug,
  Ticket,
  Workflow,
} from 'lucide-react'

// O bridge devolve uma chave de ícone por serviço; o mapa mantém o catálogo
// desenhado no backend sem acoplar o front aos nomes da biblioteca.
const ICONS = {
  activity: Activity,
  cast: Cast,
  chart: BarChart3,
  database: Database,
  key: KeyRound,
  messages: MessagesSquare,
  monitor: Monitor,
  plug: Plug,
  ticket: Ticket,
  workflow: Workflow,
}

export function serviceIcon(name) {
  return ICONS[name] || Box
}
