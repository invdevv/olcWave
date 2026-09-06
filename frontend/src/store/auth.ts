function decodeToken(token: string): string {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]))
    return payload.sub || payload.username || payload.preferred_username || ''
  } catch {
    return ''
  }
}

function getUsername(): string {
  const token = localStorage.getItem('token')
  if (!token) return ''
  return decodeToken(token)
}

import { create } from 'zustand'
import type { AuthState, LoginPayload } from '../types'
import { authApi } from '../api/auth'

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem('token'),
  username: getUsername(),
  isAuthenticated: !!localStorage.getItem('token'),

  login: async (payload: LoginPayload) => {
    const { data } = await authApi.login(payload)
    localStorage.setItem('token', data.access_token)
    const username = decodeToken(data.access_token) || payload.username
    set({ token: data.access_token, username, isAuthenticated: true })
  },

  logout: () => {
    localStorage.removeItem('token')
    set({ token: null, username: '', isAuthenticated: false })
    window.location.href =
      (import.meta.env.BASE_URL || '/').replace(/\/+$/, '') + '/login'
  },

  setToken: (token: string) => {
    localStorage.setItem('token', token)
    const username = decodeToken(token)
    set({ token, username, isAuthenticated: true })
  },
}))
