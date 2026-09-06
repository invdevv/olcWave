export interface LoginPayload {
  username: string
  password: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export interface User {
  short_uuid: string
  name?: string | null
  created_at: string
  expires_at: string
  traffic_limit_bytes: number
  traffic_used_bytes: number
  profiles?: string[] | null
}

export interface SyncResult {
  created: number
  updated: number
  deleted: number
}

export interface Profile {
  name: string
  tag: string
  profile: string
}

export interface Container {
  id: string
  name: string
  short_uuid: string
  config_tag: string
  status: string
  created: string
  image: string
}

export interface ContainerStats {
  name: string
  upload_bytes: number
  download_bytes: number
  total_bytes: number
  upload_rate_bps: number
  download_rate_bps: number
}

export interface TrafficInfo {
  short_uuid: string
  limit: number
  used: number
  remaining: number
  unlimited: boolean
  exceeded: boolean
}

export interface ContainerLogs {
  name: string
  logs: string
}

export interface ContainerConfig {
  name: string
  config: string
}

export interface ApiError {
  detail: string
}

export interface ValidationError {
  path: string
  message: string
}

export interface ValidationWarning {
  path: string
  message: string
}

export interface YamlValidationResult {
  valid: boolean
  errors: ValidationError[]
  warnings: ValidationWarning[]
}

export interface TagValidationResult {
  valid: boolean
  message?: string
}

export interface AuthState {
  token: string | null
  username: string
  isAuthenticated: boolean
  login: (payload: LoginPayload) => Promise<void>
  logout: () => void
  setToken: (token: string) => void
}
