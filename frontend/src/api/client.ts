import axios from 'axios'

const LOGIN_PATH =
  (import.meta.env.BASE_URL || '/').replace(/\/+$/, '') + '/login'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      if (window.location.pathname !== LOGIN_PATH) {
        window.location.href = LOGIN_PATH
      }
    }
    return Promise.reject(error)
  }
)

export default api
