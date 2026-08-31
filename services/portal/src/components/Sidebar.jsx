import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import {
  Calculator,
  ChevronDown,
  LayoutDashboard,
  LayoutGrid,
  LogOut,
  Menu,
  Receipt,
  Server,
  Ticket,
  User,
  X,
} from 'lucide-react'
import { serviceIcon } from './icons'

const OPERATION_ITEMS = [
  { path: '/', icon: LayoutDashboard, label: 'Painel', end: true },
  { path: '/chamados', icon: Ticket, label: 'Chamados' },
  { path: '/sla', icon: Calculator, label: 'Prazos de SLA' },
  { path: '/faturamento', icon: Receipt, label: 'Faturamento' },
  { path: '/servicos', icon: Server, label: 'Status dos serviços' },
]

const CATEGORY_LABELS = {
  itsm: 'Núcleo ITSM',
  operacao: 'Operação',
  plataforma: 'Plataforma',
}

function NavLink({ to, icon: Icon, label, active, badge, onNavigate }) {
  return (
    <Link
      to={to}
      onClick={onNavigate}
      className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-all ${
        active ? 'bg-blue-600/20 text-blue-400' : 'text-slate-400 hover:bg-slate-800 hover:text-white'
      }`}
    >
      <Icon size={18} />
      <span className="flex-1 truncate">{label}</span>
      {badge}
    </Link>
  )
}

export default function Sidebar({ user, services = [], health = {}, onLogout }) {
  const location = useLocation()
  const [isOpen, setIsOpen] = useState(false)
  const [collapsed, setCollapsed] = useState({})

  const close = () => setIsOpen(false)
  const grouped = services.reduce((acc, service) => {
    ;(acc[service.category] ||= []).push(service)
    return acc
  }, {})

  return (
    <>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="lg:hidden fixed top-4 left-4 z-50 p-2 bg-slate-800 border border-slate-700 rounded-lg text-white"
        aria-label="Menu"
      >
        {isOpen ? <X size={20} /> : <Menu size={20} />}
      </button>

      <aside
        className={`fixed inset-y-0 left-0 z-40 w-64 bg-slate-900 border-r border-slate-800 overflow-y-auto transform transition-transform duration-200 lg:translate-x-0 ${
          isOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex flex-col min-h-full">
          <div className="p-4 border-b border-slate-800 flex items-center gap-2">
            <span className="p-1.5 rounded-lg bg-blue-600/20 text-blue-400">
              <LayoutGrid size={18} />
            </span>
            <div>
              <h1 className="text-sm font-bold text-white leading-tight">Painel ITSM</h1>
              <p className="text-[11px] text-slate-500">Sistema de Chamados</p>
            </div>
          </div>

          <nav className="flex-1 p-3 space-y-4">
            <div className="space-y-1">
              {OPERATION_ITEMS.map((item) => (
                <NavLink
                  key={item.path}
                  to={item.path}
                  icon={item.icon}
                  label={item.label}
                  onNavigate={close}
                  active={
                    item.end
                      ? location.pathname === item.path
                      : location.pathname.startsWith(item.path)
                  }
                />
              ))}
            </div>

            {Object.entries(CATEGORY_LABELS).map(([category, label]) => {
              const items = grouped[category] || []
              if (items.length === 0) return null
              const isCollapsed = collapsed[category]
              return (
                <div key={category} className="space-y-1">
                  <button
                    onClick={() => setCollapsed((state) => ({ ...state, [category]: !isCollapsed }))}
                    className="w-full flex items-center gap-1 px-3 text-[11px] font-semibold uppercase tracking-wide text-slate-600 hover:text-slate-400"
                  >
                    <ChevronDown
                      size={12}
                      className={`transition-transform ${isCollapsed ? '-rotate-90' : ''}`}
                    />
                    {label}
                  </button>
                  {!isCollapsed &&
                    items.map((service) => {
                      const status = health[service.slug]?.status
                      return (
                        <NavLink
                          key={service.slug}
                          to={`/servicos/${service.slug}`}
                          icon={serviceIcon(service.icon)}
                          label={service.name}
                          onNavigate={close}
                          active={location.pathname === `/servicos/${service.slug}`}
                          badge={
                            status && status !== 'online' ? (
                              <span
                                className="w-1.5 h-1.5 rounded-full bg-red-500"
                                title="Serviço fora do ar"
                              />
                            ) : null
                          }
                        />
                      )
                    })}
                </div>
              )
            })}
          </nav>

          <div className="p-3 border-t border-slate-800 space-y-2">
            <div className="flex items-center gap-2 px-3 py-2">
              <User size={16} className="text-slate-500" />
              <div className="flex-1 min-w-0">
                <p className="text-sm text-white truncate">{user?.full_name || user?.username}</p>
                <p className="text-xs text-slate-500 truncate">
                  {user?.profile || (user?.source === 'sso' ? 'SSO' : 'GLPI')}
                </p>
              </div>
            </div>
            <button
              onClick={onLogout}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm font-medium text-red-400 hover:bg-red-900/30 transition-all"
            >
              <LogOut size={16} />
              Sair
            </button>
          </div>
        </div>
      </aside>
    </>
  )
}
