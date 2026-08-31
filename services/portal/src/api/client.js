import axios from 'axios'

// O bundle é servido pelo mesmo host do /api (nginx faz proxy para o
// itsm-bridge), então tudo é same-origin: sem CORS e sem URL de API embutida.
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '',
  headers: { 'Content-Type': 'application/json' },
})

export const TOKEN_KEY = 'itsm-portal-token'
export const USER_KEY = 'itsm-portal-user'

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    // 401 em qualquer chamada significa sessão perdida: derruba e volta ao login
    if (error.response?.status === 401 && localStorage.getItem(TOKEN_KEY)) {
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
      window.location.reload()
    }
    return Promise.reject(error)
  },
)

export function apiMessage(error, fallback = 'Falha ao falar com o servidor') {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg
  return error?.message || fallback
}

export const authApi = {
  login: (data) => api.post('/api/portal/auth/login', data).then((res) => res.data),
  me: () => api.get('/api/portal/auth/me').then((res) => res.data),
  logout: () => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  },
}

export const servicesApi = {
  list: () => api.get('/api/portal/services').then((res) => res.data),
  status: () => api.get('/api/portal/services/status').then((res) => res.data),
}

export const ticketsApi = {
  list: (params = {}) => api.get('/api/portal/tickets', { params }).then((res) => res.data),
  get: (id) => api.get(`/api/portal/tickets/${id}`).then((res) => res.data),
  create: (data) => api.post('/api/portal/tickets', data).then((res) => res.data),
  addFollowup: (id, data) =>
    api.post(`/api/portal/tickets/${id}/followups`, data).then((res) => res.data),
  solve: (id, data) => api.post(`/api/portal/tickets/${id}/solution`, data).then((res) => res.data),
  summary: () => api.get('/api/portal/summary').then((res) => res.data),
}

export const slaApi = {
  deadline: (data) => api.post('/api/sla/deadline', data).then((res) => res.data),
}

export const billingApi = {
  preview: (data) => api.post('/api/billing/invoices/preview', data).then((res) => res.data),
}

export default api
