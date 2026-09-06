import api from './client'

// Panel-facing proxy to the auth-token vault sidecar (admin-authed on the
// backend). The noVNC stream itself is loaded straight from the panel origin
// (proxied by Caddy), not through this client.
export const vaultApi = {
  loginStart: (account?: string) =>
    api.post<{ account: string; novnc?: string }>(
      '/vault/login/start',
      null,
      { params: account ? { account } : {} },
    ),
  loginCommit: () =>
    api.post<{ account: string; ok?: boolean; len?: number; token?: string | null; error?: string }>(
      '/vault/login/commit',
    ),
  loginCancel: () => api.post('/vault/login/cancel'),
  loginStatus: () =>
    api.get<{
      live: string | null
      sid?: boolean
      sidFp?: string | null
      url?: string
      ready?: boolean
    }>('/vault/login/status'),
  accounts: () => api.get<{ accounts: string[] }>('/vault/accounts'),
}
