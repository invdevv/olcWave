import { load } from 'js-yaml'
import type { ValidationError, ValidationWarning, YamlValidationResult } from '../types'

const ALLOWED_PROVIDERS = ['jitsi', 'telemost', 'wbstream', 'none']
const ALLOWED_TRANSPORTS = ['datachannel', 'vp8channel', 'seichannel', 'videochannel']
const DURATION_RE = /^\d+[smhd]$/
const DELAY_RE = /^\d+ms$/
const HOST_PORT_RE = /^.+:\d+$/

function addError(errors: ValidationError[], path: string, message: string) {
  errors.push({ path, message })
}

function addWarning(warnings: ValidationWarning[], path: string, message: string) {
  warnings.push({ path, message })
}

export function validateYaml(yaml: string): YamlValidationResult {
  const errors: ValidationError[] = []
  const warnings: ValidationWarning[] = []

  if (!yaml.trim()) {
    return { valid: true, errors, warnings }
  }

  let doc: unknown
  try {
    doc = load(yaml)
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : 'Invalid YAML'
    addError(errors, '', msg)
    return { valid: false, errors, warnings }
  }

  if (!doc || typeof doc !== 'object' || Array.isArray(doc)) {
    addError(errors, '', 'YAML root must be a mapping (object)')
    return { valid: false, errors, warnings }
  }

  const root = doc as Record<string, unknown>

  // mode — warning only
  if ('mode' in root) {
    addWarning(warnings, 'mode', 'Optional field; backend will force to "srv"')
  }

  // auth
  const auth = root.auth as Record<string, unknown> | undefined
  const provider = auth?.provider as string | undefined

  if (provider !== undefined) {
    if (!ALLOWED_PROVIDERS.includes(provider)) {
      addError(errors, 'auth.provider', `Must be one of: ${ALLOWED_PROVIDERS.join(', ')}`)
    }
  }

  // room.id validation
  const room = root.room as Record<string, unknown> | undefined
  if (provider && provider !== 'none') {
    if (provider === 'telemost' || provider === 'wbstream') {
      const token = auth?.token as string | undefined
      const tokens = auth?.tokens as unknown[] | undefined
      // A token is present via a single auth.token OR a non-empty auth.tokens list
      // (multi-account rotation). A tokens entry may be a plain string, or a
      // managed/self-refreshing object { token, account }. Either one lets the
      // room be auto-generated.
      const hasToken =
        (typeof token === 'string' && token.trim() !== '') ||
        (Array.isArray(tokens) &&
          tokens.some(
            (x) =>
              (typeof x === 'string' && x.trim() !== '') ||
              (!!x &&
                typeof x === 'object' &&
                typeof (x as { token?: unknown }).token === 'string' &&
                (x as { token: string }).token.trim() !== ''),
          ))
      if (!hasToken) {
        if (!room?.id) {
          addError(errors, 'room.id', 'Required when auth.provider is set and no token(s) set')
        }
      } else {
        if (room?.id) {
          addWarning(warnings, 'room.id', 'Generated automatically when a token is set')
        }
      }
    } else {
      if (!room?.id) {
        addError(errors, 'room.id', 'Required when auth.provider is set')
      }
    }
  }

  // crypto — warning only
  if ('crypto' in root) {
    addWarning(warnings, 'crypto', 'Optional field; crypto.key will be auto-generated')
  }

  // net
  const net = root.net as Record<string, unknown> | undefined
  const transport = net?.transport as string | undefined

  if (transport !== undefined) {
    if (!ALLOWED_TRANSPORTS.includes(transport)) {
      addError(errors, 'net.transport', `Must be one of: ${ALLOWED_TRANSPORTS.join(', ')}`)
    }
  }

  const dns = net?.dns as string | undefined
  if (dns !== undefined) {
    if (!HOST_PORT_RE.test(dns)) {
      addError(errors, 'net.dns', 'Must be in host:port format (e.g., "8.8.8.8:53")')
    }
  }

  // transport-dependent sections
  if (transport === 'videochannel' && !root.video) {
    addError(errors, 'video', 'Required when net.transport is "videochannel"')
  }
  if (transport === 'vp8channel' && !root.vp8) {
    addError(errors, 'vp8', 'Required when net.transport is "vp8channel"')
  }
  if (transport === 'seichannel' && !root.sei) {
    addError(errors, 'sei', 'Required when net.transport is "seichannel"')
  }

  // engine — only allowed when provider === 'none'
  const engine = root.engine as Record<string, unknown> | undefined
  if (engine !== undefined) {
    if (provider !== 'none') {
      addError(errors, 'engine', 'Only allowed when auth.provider is "none"')
    } else {
      if (!engine.name) addError(errors, 'engine.name', 'Required when engine section is present')
      if (!engine.url) addError(errors, 'engine.url', 'Required when engine section is present')
      if (!engine.token) addError(errors, 'engine.token', 'Required when engine section is present')
    }
  }

  // liveness
  const liveness = root.liveness as Record<string, unknown> | undefined
  if (liveness) {
    if (liveness.interval !== undefined && !DURATION_RE.test(String(liveness.interval))) {
      addError(errors, 'liveness.interval', 'Must be a duration (e.g., "10s", "1m", "5m")')
    }
    if (liveness.timeout !== undefined && !DURATION_RE.test(String(liveness.timeout))) {
      addError(errors, 'liveness.timeout', 'Must be a duration (e.g., "10s", "1m")')
    }
    if (liveness.failures !== undefined) {
      if (typeof liveness.failures !== 'number' || liveness.failures < 0) {
        addError(errors, 'liveness.failures', 'Must be a non-negative number')
      }
    }
  }

  // lifecycle
  const lifecycle = root.lifecycle as Record<string, unknown> | undefined
  const maxSession = lifecycle?.max_session_duration as string | undefined
  if (maxSession !== undefined && !DURATION_RE.test(String(maxSession))) {
    addError(errors, 'lifecycle.max_session_duration', 'Must be a duration (e.g., "6h", "30m", "1d")')
  }

  // traffic
  const traffic = root.traffic as Record<string, unknown> | undefined
  if (traffic) {
    const payload = traffic.max_payload_size as number | undefined
    if (payload !== undefined && (typeof payload !== 'number' || payload < 0)) {
      addError(errors, 'traffic.max_payload_size', 'Must be a non-negative number')
    }

    const minDelay = traffic.min_delay as string | undefined
    if (minDelay !== undefined && !DELAY_RE.test(String(minDelay))) {
      addError(errors, 'traffic.min_delay', 'Must be in milliseconds (e.g., "5ms", "30ms")')
    }

    const maxDelay = traffic.max_delay as string | undefined
    if (maxDelay !== undefined && !DELAY_RE.test(String(maxDelay))) {
      addError(errors, 'traffic.max_delay', 'Must be in milliseconds (e.g., "5ms", "30ms")')
    }
  }

  // socks — warning
  if ('socks' in root) {
    addWarning(warnings, 'socks', 'Will be removed by backend')
  }

  // data — warning only
  if ('data' in root) {
    addWarning(warnings, 'data', 'Optional field; backend will delete it')
  }

  return { valid: errors.length === 0, errors, warnings }
}