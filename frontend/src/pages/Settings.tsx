import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { settingsApi, type RuntimeSettings } from '../api/settings'
import { useAuthStore } from '../store/auth'
import { useLanguage, type TranslationKey } from '../i18n/useLanguage'
import Button from '../components/ui/Button'
import Input from '../components/ui/Input'
import Select from '../components/ui/Select'
import { Card, CardHeader } from '../components/ui/Misc'
import { ToastContainer } from '../components/containers/Toast'
import { useToasts } from '../components/containers/useToasts'
import { bytesToGB, gbToBytes } from '../utils/format'
import {
  ArrowLeftOnRectangleIcon,
  ExclamationTriangleIcon,
} from '@heroicons/react/24/outline'

const RW_SYNC_OPTIONS: { value: string; labelKey: TranslationKey }[] = [
  { value: '1m', labelKey: 'everyMinute' },
  { value: '5m', labelKey: 'every5Minutes' },
  { value: '15m', labelKey: 'every15Minutes' },
  { value: '1h', labelKey: 'everyHour' },
  { value: '6h', labelKey: 'every6Hours' },
  { value: '12h', labelKey: 'every12Hours' },
  { value: '24h', labelKey: 'onceADay' },
  { value: '__other__', labelKey: 'other' },
]

function isValidInterval(val: string): boolean {
  return /^[1-9]\d*[mh]$/.test(val)
}

function isValidDuration(val: string): boolean {
  return /^[1-9]\d*[mhd]$/.test(val)
}

function parseDurationMinutes(val: string): number | null {
  const match = val.match(/^(\d+)([mhd])$/)
  if (!match) return null
  const number = parseInt(match[1], 10)
  const unit = match[2]
  const multiplier: Record<string, number> = { m: 1, h: 60, d: 1440 }
  return number * multiplier[unit]
}

function getDurationError(val: string, tr: (key: TranslationKey) => string): string {
  if (!isValidDuration(val)) {
    return tr('invalidFormatDuration')
  }
  const minutes = parseDurationMinutes(val)
  if (minutes === null) return tr('invalidDuration')
  if (minutes < 5) return tr('intervalMin5m')
  if (minutes > 43200) return tr('intervalMax30d')
  return ''
}

function formatDatetime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString() + ' ' + d.toLocaleTimeString()
}

export default function Settings() {
  const { t } = useLanguage()
  const logout = useAuthStore((s) => s.logout)
  const { toasts, dismiss, success, error: toastError } = useToasts()
  const queryClient = useQueryClient()

  const { data: rwEnabled } = useQuery({
    queryKey: ['rw-enabled'],
    queryFn: () => settingsApi.getRwEnabled(),
    staleTime: Infinity,
  })

  const { data: settings, isLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: () => settingsApi.get().then((r) => r.data),
  })

  const [subName, setSubName] = useState('')
  const [defaultTrafficGb, setDefaultTrafficGb] = useState('')
  const [subUpdateInterval, setSubUpdateInterval] = useState('')
  const [collectInterval, setCollectInterval] = useState('')
  const [syncMode, setSyncMode] = useState('1h')
  const [customSync, setCustomSync] = useState('')
  const [lastSyncAt, setLastSyncAt] = useState<string | null>(null)
  const [rotationMode, setRotationMode] = useState<'prod' | 'test'>('prod')

  useEffect(() => {
    if (!settings) return

    setSubName(settings.sub_name)
    setDefaultTrafficGb(bytesToGB(settings.default_traffic_limit).toFixed(2))
    setSubUpdateInterval(settings.sub_update_interval)
    setCollectInterval(String(settings.traffic_collect_interval))
    if (RW_SYNC_OPTIONS.some(o => o.value === settings.sync_interval)) {
      setSyncMode(settings.sync_interval)
      setCustomSync('')
    } else {
      setSyncMode('__other__')
      setCustomSync(settings.sync_interval)
    }
    setLastSyncAt(settings.last_sync_at)
    setRotationMode(settings.rotation_mode ?? 'prod')
  }, [settings])

  const saveMutation = useMutation({
    mutationFn: (data: RuntimeSettings) => settingsApi.update(data).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings'] })
      success(t('settingsSaved'))
    },
    onError: (err) => {
      toastError(
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
          t('failedToSaveSettings'),
      )
    },
  })

  const isCustom = syncMode === '__other__'
  const effectiveSync = isCustom
    ? customSync
    : syncMode
  const syncError = isCustom && customSync && !isValidInterval(customSync) ? t('invalidFormatNumberSuffix') : ''
  const subIntervalError = subUpdateInterval ? getDurationError(subUpdateInterval, t) : ''

  const handleSave = () => {
    saveMutation.mutate({
      sub_name: subName,
      default_traffic_limit: gbToBytes(parseFloat(defaultTrafficGb) || 0),
      sub_update_interval: subUpdateInterval || '1h',
      traffic_collect_interval: parseInt(collectInterval, 10) || 10,
      sync_interval: effectiveSync || '1h',
      last_sync_at: lastSyncAt,
      rotation_mode: rotationMode,
    })
  }

  // The rotation toggle applies instantly. Build the payload from the last-saved
  // `settings` (not the editable fields) so flipping the switch never depends on -
  // or accidentally commits - unsaved edits in the other cards.
  const handleRotationChange = (value: string) => {
    const mode: 'prod' | 'test' = value === 'test' ? 'test' : 'prod'
    setRotationMode(mode)
    if (!settings) return
    saveMutation.mutate({ ...settings, rotation_mode: mode })
  }

  const handleSyncSelect = (value: string) => {
    setSyncMode(value)

    if (value !== '__other__') {
      setCustomSync('')
    }
  }

  return (
    <div className="max-w-2xl space-y-5">
      <Card>
        <CardHeader title={t('trafficSettingsTitle')} />
        <div className="px-5 py-4 space-y-4">
          <Input
            label={t('subscriptionName')}
            value={subName}
            onChange={(e) => setSubName(e.target.value)}
            placeholder={t('myVpn')}
            hint={t('serviceNameHint')}
            disabled={isLoading}
          />
          <Input
            label={t('defaultTrafficLimitGb')}
            type="number"
            min="0"
            step="0.1"
            value={defaultTrafficGb}
            onChange={(e) => setDefaultTrafficGb(e.target.value)}
            placeholder={t('trafficLimitPlaceholder')}
            hint={t('defaultTrafficHint')}
            disabled={isLoading}
          />
          <Input
            label={t('subscriptionUpdateInterval')}
            value={subUpdateInterval}
            onChange={(e) => setSubUpdateInterval(e.target.value)}
            placeholder="e.g. 1h"
            hint={t('subIntervalHint')}
            error={subIntervalError}
            disabled={isLoading}
          />
          <Input
            label={t('trafficCollectInterval')}
            type="number"
            min="1"
            step="1"
            value={collectInterval}
            onChange={(e) => setCollectInterval(e.target.value)}
            placeholder="e.g. 10"
            hint={t('trafficCollectHint')}
            disabled={isLoading}
          />
          <div className="flex justify-end pt-1">
            <Button onClick={handleSave} loading={saveMutation.isPending} disabled={isLoading || !!subIntervalError}>
              {t('saveSettings')}
            </Button>
          </div>
        </div>
      </Card>

      <Card>
        <CardHeader title={t('rotationTitle')} />
        <div className="px-5 py-4 space-y-3">
          <Select
            label={t('rotationModeLabel')}
            options={[
              { value: 'prod', label: t('rotationModeProd') },
              { value: 'test', label: t('rotationModeTest') },
            ]}
            value={rotationMode}
            onChange={(e) => handleRotationChange(e.target.value)}
            disabled={isLoading || saveMutation.isPending}
          />
          <p className="text-xs text-text-muted">{t('rotationHint')}</p>
          {rotationMode === 'test' && (
            <div className="flex items-center gap-2 bg-warning/10 border border-warning/20 rounded-lg px-3 py-2 text-xs text-warning">
              <ExclamationTriangleIcon className="w-4 h-4 shrink-0" />
              <span>{t('rotationTestWarn')}</span>
            </div>
          )}
        </div>
      </Card>

      {rwEnabled === true && (
        <Card>
          <CardHeader title={t('remnawaveSync')} />
          <div className="px-5 py-4 space-y-4">
            <Select
              label={t('autoSyncUsers')}
              options={RW_SYNC_OPTIONS.map((o) => ({ value: o.value, label: t(o.labelKey) }))}
              value={syncMode}
              onChange={(e) => handleSyncSelect(e.target.value)}
              disabled={isLoading}
            />
            {isCustom && (
              <Input
                label={t('customInterval')}
                value={customSync}
                onChange={(e) => setCustomSync(e.target.value)}
                placeholder="e.g. 10m"
                error={syncError}
                hint={t('customIntervalHint')}
                disabled={isLoading}
              />
            )}
            <div className="flex items-center justify-between gap-4 py-2 border-t border-border">
              <span className="text-xs text-text-muted">{t('lastSync')}</span>
              <span className="text-xs text-text-primary tabular-nums">{formatDatetime(lastSyncAt)}</span>
            </div>
            <div className="flex justify-end pt-1">
              <Button
                onClick={handleSave}
                loading={saveMutation.isPending}
                disabled={isLoading || !!syncError}
              >
                {t('saveSettings')}
              </Button>
            </div>
          </div>
        </Card>
      )}

      <Card className="border-danger/20">
        <div className="px-5 py-3.5 border-b border-danger/20 flex items-center gap-2">
          <ExclamationTriangleIcon className="w-4 h-4 text-danger" />
          <h3 className="text-xs font-semibold text-danger uppercase tracking-wider">{t('dangerZone')}</h3>
        </div>
        <div className="p-5 flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-text-primary">{t('signOut')}</p>
            <p className="text-xs text-text-muted mt-0.5">{t('signOutDescription')}</p>
          </div>
          <Button variant="danger" onClick={logout}>
            <ArrowLeftOnRectangleIcon className="w-4 h-4" />
            {t('logout')}
          </Button>
        </div>
      </Card>

      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </div>
  )
}
