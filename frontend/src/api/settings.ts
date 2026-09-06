import api from './client'

export interface RuntimeSettings {
  sub_name: string
  default_traffic_limit: number
  sub_update_interval: string
  traffic_collect_interval: number
  sync_interval: string
  last_sync_at: string | null
  rotation_mode: 'prod' | 'test'
}

export const settingsApi = {
  get: () =>
    api.get<RuntimeSettings>('/settings/'),

  update: (data: RuntimeSettings) =>
    api.put<RuntimeSettings>('/settings/', data),

  getRwEnabled: () =>
    api.get<boolean>('/settings/rw_enabled').then((r) => r.data),
}
