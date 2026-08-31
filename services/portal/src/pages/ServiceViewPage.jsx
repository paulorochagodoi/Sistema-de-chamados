import { Navigate, useParams } from 'react-router-dom'
import ServiceFrame from '../components/ServiceFrame'
import { Loading } from '../components/ui'

export default function ServiceViewPage({ services = [], health = {} }) {
  const { slug } = useParams()

  // O catálogo ainda pode estar carregando quando a rota abre direto pela URL.
  if (services.length === 0) return <Loading />

  const service = services.find((item) => item.slug === slug)
  if (!service) return <Navigate to="/servicos" replace />

  return <ServiceFrame service={service} health={health[slug]} />
}
