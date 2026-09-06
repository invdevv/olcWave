import { useState, useMemo, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { usersApi } from '../api/users'
import { profilesApi } from '../api/profiles'
import { settingsApi } from '../api/settings'
import type { User, SyncResult, Profile } from '../types'
import Button from '../components/ui/Button'
import Badge from '../components/ui/Badge'
import Input from '../components/ui/Input'
import Modal from '../components/ui/Modal'
import ConfirmDialog from '../components/ui/ConfirmDialog'
import ProgressBar from '../components/ui/ProgressBar'
import AutoRefreshSelect from '../components/ui/AutoRefreshSelect'
import { Card, ErrorState, EmptyState, Skeleton } from '../components/ui/Misc'
import { ToastContainer } from '../components/containers/Toast'
import { useToasts } from '../components/containers/useToasts'
import { useAutoRefresh } from '../utils/useAutoRefresh'
import { useLanguage } from '../i18n/useLanguage'
import { formatBytes, trafficPercent, bytesToGB, gbToBytes, buildSubUrl } from '../utils/format'
import {
  MagnifyingGlassIcon,
  TrashIcon,
  ArrowPathIcon,
  UsersIcon,
  ClipboardDocumentIcon,
  CheckIcon,
  LinkIcon,
  PlusIcon,
} from '@heroicons/react/24/outline'

function generateShortUuid(): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (b) => chars[b % chars.length]).join('')
}

export default function Users() {
  const { t } = useLanguage()
  const [search, setSearch] = useState('')
  const [editUser, setEditUser] = useState<User | null>(null)
  const [deleteUser, setDeleteUser] = useState<User | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [refreshMs, setRefreshMs] = useAutoRefresh('users')
  const { toasts, dismiss, success, error: toastError } = useToasts()
  const queryClient = useQueryClient()

  const { data: rwEnabled } = useQuery({
    queryKey: ['rw-enabled'],
    queryFn: () => settingsApi.getRwEnabled(),
    staleTime: Infinity,
  })

  const { data: users, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ['users-all'],
    queryFn: () => usersApi.getAll().then((r) => r.data),
    refetchInterval: refreshMs || false,
  })

  const deleteMutation = useMutation({
    mutationFn: (uuid: string) => usersApi.delete(uuid),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users-all'] })
      setDeleteUser(null)
    },
  })

  const syncMutation = useMutation({
    mutationFn: () => usersApi.syncWithRemnawave().then((r) => r.data),
    onSuccess: (data: SyncResult) => {
      queryClient.invalidateQueries({ queryKey: ['users-all'] })
      success(t('syncResult', { created: data.created, updated: data.updated, deleted: data.deleted }))
    },
    onError: (err) => {
      toastError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || t('failedToSync'))
    },
  })

  const filtered = useMemo(() => {
    if (!users) return []
    const q = search.toLowerCase()
    return users.filter(
      (u) =>
        (u.name || '').toLowerCase().includes(q) ||
        u.short_uuid.toLowerCase().includes(q) ||
        u.created_at.toLowerCase().includes(q) ||
        u.expires_at.toLowerCase().includes(q)
    )
  }, [users, search])

  const copySubUrl = (user: User) => {
    navigator.clipboard.writeText(buildSubUrl(user.short_uuid))
    success(t('copied'))
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[220px]">
          <MagnifyingGlassIcon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('filterUsers')}
            className="w-full h-9 bg-bg-tertiary border border-border rounded-md pl-9 pr-3 text-sm text-text-primary
              placeholder:text-text-muted focus:outline-none focus:border-accent focus:ring-2 focus:ring-accent/30 transition-all"
          />
        </div>
        <span className="text-xs text-text-muted tabular-nums">{t('nUsers', { n: filtered.length })}</span>
        <AutoRefreshSelect value={refreshMs} onChange={setRefreshMs} />
        {rwEnabled === true && (
          <Button variant="secondary" onClick={() => syncMutation.mutate()} loading={syncMutation.isPending} disabled={syncMutation.isPending}>
            <ArrowPathIcon className={`w-4 h-4 ${syncMutation.isPending ? 'animate-spin' : ''}`} />
            {t('syncWithRemnawave')}
          </Button>
        )}
        {rwEnabled === false && (
          <Button variant="primary" onClick={() => setShowCreate(true)}>
            <PlusIcon className="w-4 h-4" />
            {t('addUser')}
          </Button>
        )}
        <Button variant="secondary" onClick={() => refetch()}>
          <ArrowPathIcon className={`w-4 h-4 ${isFetching ? 'animate-spin' : ''}`} />
          {t('refresh')}
        </Button>
      </div>

      {isError ? (
        <Card>
          <ErrorState
            message={(error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || t('failedToLoadUsers')}
            onRetry={() => refetch()}
          />
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left bg-bg-tertiary/40">
                  <Th>{t('nameShortUuid')}</Th>
                  <Th>{t('created')}</Th>
                  <Th>{t('expires')}</Th>
                  <Th>{t('traffic')}</Th>
                  <Th>{t('status')}</Th>
                  <Th className="text-right">{t('actions')}</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {isLoading &&
                  Array.from({ length: 6 }).map((_, i) => (
                    <tr key={i}>
                      <td className="px-5 py-3"><Skeleton className="h-4 w-24" /></td>
                      <td className="px-5 py-3"><Skeleton className="h-4 w-32" /></td>
                      <td className="px-5 py-3"><Skeleton className="h-4 w-32" /></td>
                      <td className="px-5 py-3"><Skeleton className="h-4 w-28" /></td>
                      <td className="px-5 py-3"><Skeleton className="h-5 w-16 rounded-full" /></td>
                      <td className="px-5 py-3"><Skeleton className="h-4 w-12 ml-auto" /></td>
                    </tr>
                  ))}
                {!isLoading && filtered.length === 0 && (
                  <tr>
                    <td colSpan={6}>
                      <EmptyState
                        message={users?.length === 0 ? t('noUsersFound') : t('noMatchingUsers')}
                        hint={users?.length === 0 ? undefined : t('tryAdjustingSearch')}
                        icon={<UsersIcon className="w-6 h-6" />}
                      />
                    </td>
                  </tr>
                )}
                {!isLoading &&
                  filtered.map((user) => (
                    <UserRow
                      key={user.short_uuid}
                      user={user}
                      onOpen={() => setEditUser(user)}
                      onDelete={() => setDeleteUser(user)}
                      onCopySubUrl={() => copySubUrl(user)}
                    />
                  ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <UserCreateModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={() => {
          setShowCreate(false)
          queryClient.invalidateQueries({ queryKey: ['users-all'] })
        }}
        onToast={success}
        onError={toastError}
      />
      <UserEditModal
        user={editUser}
        onClose={() => setEditUser(null)}
        onDeleted={() => setEditUser(null)}
        onCopySubUrl={copySubUrl}
        onToast={success}
        onError={toastError}
      />
      <ConfirmDialog
        open={!!deleteUser}
        onClose={() => setDeleteUser(null)}
        onConfirm={() => deleteUser && deleteMutation.mutate(deleteUser.short_uuid)}
        title={t('deleteUser')}
        message={t('deleteUserConfirm', { uuid: deleteUser?.short_uuid || '' })}
        loading={deleteMutation.isPending}
      />
      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </div>
  )
}

function Th({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <th className={`px-5 py-3 text-xs font-semibold text-text-muted uppercase tracking-wider ${className}`}>
      {children}
    </th>
  )
}

function StatBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-bg-tertiary border border-border rounded-lg px-3 py-2.5">
      <p className="text-[10px] uppercase tracking-wider text-text-muted">{label}</p>
      <p className="text-sm font-semibold text-text-primary mt-0.5 tabular-nums">{value}</p>
    </div>
  )
}

function UserRow({
  user,
  onOpen,
  onDelete,
  onCopySubUrl,
}: {
  user: User
  onOpen: () => void
  onDelete: () => void
  onCopySubUrl: () => void
}) {
  const { t } = useLanguage()
  const [copied, setCopied] = useState(false)
  const isExpired = new Date(user.expires_at) < new Date()
  const created = new Date(user.created_at)
  const expires = new Date(user.expires_at)
  const unlimited = user.traffic_limit_bytes === 0
  const percent = trafficPercent(user.traffic_used_bytes, user.traffic_limit_bytes)
  const exceeded = !unlimited && user.traffic_used_bytes >= user.traffic_limit_bytes

  const copyUuid = (e: React.MouseEvent) => {
    e.stopPropagation()
    navigator.clipboard.writeText(user.short_uuid)
    setCopied(true)
    setTimeout(() => setCopied(false), 1200)
  }

  return (
    <tr
      onClick={onOpen}
      className="hover:bg-bg-hover transition-colors group cursor-pointer"
    >
      <td className="px-5 py-3">
        <div className="flex items-center gap-2">
          <div className="min-w-0">
            {user.name ? (
              <>
                <div className="text-sm font-medium text-text-primary truncate max-w-[200px]">{user.name}</div>
                <div className="flex items-center gap-1.5 mt-0.5">
                  <code className="text-[11px] font-mono text-text-muted">{user.short_uuid}</code>
                  <button
                    onClick={copyUuid}
                    className="text-text-muted hover:text-text-primary transition-all cursor-pointer shrink-0"
                    title={t('copyUUID')}
                  >
                    {copied ? <CheckIcon className="w-3 h-3 text-success" /> : <ClipboardDocumentIcon className="w-3 h-3" />}
                  </button>
                </div>
              </>
            ) : (
              <div className="flex items-center gap-2">
                <code className="text-xs font-mono text-accent">{user.short_uuid}</code>
                <button
                  onClick={copyUuid}
                  className="text-text-muted hover:text-text-primary sm:opacity-0 sm:group-hover:opacity-100 transition-all cursor-pointer"
                  title={t('copyUUID')}
                >
                  {copied ? <CheckIcon className="w-3.5 h-3.5 text-success" /> : <ClipboardDocumentIcon className="w-3.5 h-3.5" />}
                </button>
              </div>
            )}
          </div>
        </div>
      </td>
      <td className="px-5 py-3 text-xs text-text-secondary whitespace-nowrap">{created.toLocaleDateString()} {created.toLocaleTimeString()}</td>
      <td className="px-5 py-3 text-xs text-text-secondary whitespace-nowrap">{expires.toLocaleDateString()} {expires.toLocaleTimeString()}</td>
      <td className="px-5 py-3">
        <div className="w-40 space-y-1">
          <div className="flex items-center justify-between gap-2 text-xs">
            <span className="text-text-secondary tabular-nums">
              {formatBytes(user.traffic_used_bytes)} / {unlimited ? '∞' : formatBytes(user.traffic_limit_bytes)}
            </span>
            {!unlimited && <span className="text-text-muted tabular-nums">{percent}%</span>}
          </div>
          <ProgressBar percent={percent} unlimited={unlimited} />
        </div>
      </td>
      <td className="px-5 py-3">
        {exceeded ? (
          <Badge variant="danger" dot>{t('trafficExceeded')}</Badge>
        ) : (
          <Badge variant={isExpired ? 'danger' : 'success'} dot>{isExpired ? t('expired') : t('active')}</Badge>
        )}
      </td>
      <td className="px-5 py-3 text-right">
        <div className="flex items-center justify-end gap-1">
          <button
            onClick={(e) => {
              e.stopPropagation()
              onCopySubUrl()
            }}
            className="p-1.5 rounded-md text-text-muted hover:text-text-primary hover:bg-bg-tertiary transition-colors cursor-pointer"
            title={t('copySubscriptionUrl')}
          >
            <LinkIcon className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation()
              onDelete()
            }}
            className="p-1.5 rounded-md text-text-muted hover:text-danger hover:bg-danger/10 transition-colors cursor-pointer"
            title={t('delete')}
          >
            <TrashIcon className="w-3.5 h-3.5" />
          </button>
        </div>
      </td>
    </tr>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <p className="text-[11px] font-semibold text-text-muted uppercase tracking-wider">{children}</p>
}

function ProfileSelector({
  profiles,
  loading,
  selected,
  onToggle,
}: {
  profiles: Profile[] | undefined
  loading: boolean
  selected: string[]
  onToggle: (tag: string) => void
}) {
  const { t } = useLanguage()
  if (loading) return <Skeleton className="h-16 rounded-lg" />
  if (!profiles || profiles.length === 0)
    return (
      <div className="bg-bg-tertiary border border-border rounded-lg p-3.5">
        <p className="text-xs text-text-muted">{t('noProfilesToAssign')}</p>
      </div>
    )
  return (
    <div className="bg-bg-tertiary border border-border rounded-lg p-3.5 space-y-2 max-h-48 overflow-y-auto">
      {profiles.map((p) => (
        <label key={p.tag} className="flex items-center gap-2 text-sm cursor-pointer select-none">
          <input
            type="checkbox"
            checked={selected.includes(p.tag)}
            onChange={() => onToggle(p.tag)}
            className="accent-accent w-4 h-4 cursor-pointer"
          />
          <span className="text-text-primary">{p.name}</span>
          <code className="text-[11px] font-mono text-text-muted">{p.tag}</code>
        </label>
      ))}
    </div>
  )
}

function UserCreateModal({
  open,
  onClose,
  onCreated,
  onToast,
  onError,
}: {
  open: boolean
  onClose: () => void
  onCreated: () => void
  onToast: (message: string) => void
  onError: (message: string) => void
}) {
  const { t } = useLanguage()
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [expiry, setExpiry] = useState('')
  const [limitGb, setLimitGb] = useState('')
  const [unlimited, setUnlimited] = useState(false)
  const [selectedProfiles, setSelectedProfiles] = useState<string[]>([])

  const { data: allProfiles, isLoading: profilesLoading } = useQuery({
    queryKey: ['profiles-all'],
    queryFn: () => profilesApi.getAll().then((r) => r.data),
  })

  useEffect(() => {
    if (open) {
      setName('')
      setExpiry('')
      setLimitGb('')
      setUnlimited(false)
    }
  }, [open])

  // Default a new user to all existing profiles.
  useEffect(() => {
    if (open) setSelectedProfiles((allProfiles ?? []).map((p) => p.tag))
  }, [open, allProfiles])

  const toggleProfile = (tag: string) =>
    setSelectedProfiles((s) => (s.includes(tag) ? s.filter((x) => x !== tag) : [...s, tag]))

  const errMsg = (err: unknown, fallback: string) =>
    (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback

  const createMutation = useMutation({
    mutationFn: async () => {
      const bytes = unlimited ? 0 : gbToBytes(parseFloat(limitGb) || 0)
      const shortUuid = generateShortUuid()
      await usersApi.create({
        short_uuid: shortUuid,
        name: name || null,
        expires_at: new Date(expiry || Date.now() + 365 * 86400000).toISOString(),
        traffic_limit_bytes: bytes,
        profiles: selectedProfiles,
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users-all'] })
      onToast(t('userCreated'))
      onCreated()
    },
    onError: (err) => onError(errMsg(err, t('failedToCreateUser'))),
  })

  return (
    <Modal open={open} onClose={onClose} title={t('createUser')} wide>
      <div className="space-y-5">
        <div className="space-y-2.5">
          <SectionLabel>{t('userInformation')}</SectionLabel>
          <div className="bg-bg-tertiary border border-border rounded-lg p-3.5 space-y-3">
            <Input
              label={t('username')}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('displayName')}
            />
          </div>
        </div>

        <div className="space-y-2.5">
          <SectionLabel>{t('trafficSettings')}</SectionLabel>
          <div className="bg-bg-tertiary border border-border rounded-lg p-3.5 space-y-3">
            <label className="flex items-center gap-2 text-sm text-text-secondary cursor-pointer select-none">
              <input
                type="checkbox"
                checked={unlimited}
                onChange={(e) => setUnlimited(e.target.checked)}
                className="accent-accent w-4 h-4 cursor-pointer"
              />
              {t('unlimitedTraffic')}
            </label>
            {!unlimited && (
              <Input
                label={t('trafficLimitGb')}
                type="number"
                min="0"
                step="0.1"
                value={limitGb}
                onChange={(e) => setLimitGb(e.target.value)}
                placeholder={t('trafficLimitPlaceholder')}
              />
            )}
          </div>
        </div>

        <div className="space-y-2.5">
          <SectionLabel>{t('timeSettings')}</SectionLabel>
          <Input
            label={t('expiresAt')}
            type="datetime-local"
            value={expiry}
            onChange={(e) => setExpiry(e.target.value)}
          />
        </div>

        <div className="space-y-2.5">
          <SectionLabel>{t('userProfiles')}</SectionLabel>
          <p className="text-xs text-text-muted">{t('userProfilesHint')}</p>
          <ProfileSelector
            profiles={allProfiles}
            loading={profilesLoading}
            selected={selectedProfiles}
            onToggle={toggleProfile}
          />
        </div>

        <div className="border-t border-border pt-4 flex items-center justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>{t('cancel')}</Button>
          <Button loading={createMutation.isPending} onClick={() => createMutation.mutate()}>
            {t('createUserButton')}
          </Button>
        </div>
      </div>
    </Modal>
  )
}

function UserEditModal({
  user,
  onClose,
  onDeleted,
  onCopySubUrl,
  onToast,
  onError,
}: {
  user: User | null
  onClose: () => void
  onDeleted: () => void
  onCopySubUrl: (user: User) => void
  onToast: (message: string) => void
  onError: (message: string) => void
}) {
  const { t } = useLanguage()
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [expiry, setExpiry] = useState('')
  const [limitGb, setLimitGb] = useState('')
  const [unlimited, setUnlimited] = useState(false)
  const [confirmReset, setConfirmReset] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [selectedProfiles, setSelectedProfiles] = useState<string[]>([])

  const { data: traffic, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['user-traffic', user?.short_uuid],
    queryFn: () => usersApi.getTraffic(user!.short_uuid).then((r) => r.data),
    enabled: !!user,
  })

  const { data: allProfiles, isLoading: profilesLoading } = useQuery({
    queryKey: ['profiles-all'],
    queryFn: () => profilesApi.getAll().then((r) => r.data),
  })

  const toggleProfile = (tag: string) =>
    setSelectedProfiles((s) => (s.includes(tag) ? s.filter((x) => x !== tag) : [...s, tag]))

  useEffect(() => {
    if (user) {
      setName(user.name || '')
      setExpiry(user.expires_at.slice(0, 16))
    }
    setConfirmReset(false)
    setConfirmDelete(false)
  }, [user])

  // null profiles = all (legacy) -> pre-check everything; a list -> exactly those.
  useEffect(() => {
    if (!user) return
    setSelectedProfiles(user.profiles ?? (allProfiles ?? []).map((p) => p.tag))
  }, [user, allProfiles])

  useEffect(() => {
    if (traffic) {
      setUnlimited(traffic.unlimited)
      setLimitGb(traffic.unlimited ? '' : bytesToGB(traffic.limit).toFixed(2))
    }
  }, [traffic])

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['users-all'] })
    queryClient.invalidateQueries({ queryKey: ['user-traffic', user?.short_uuid] })
  }

  const errMsg = (err: unknown, fallback: string) =>
    (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback

  const saveMutation = useMutation({
    mutationFn: async () => {
      const bytes = unlimited ? 0 : gbToBytes(parseFloat(limitGb) || 0)
      await usersApi.update(user!.short_uuid, {
        name: name || null,
        expires_at: new Date(expiry).toISOString(),
        traffic_limit_bytes: bytes,
        traffic_used_bytes: user!.traffic_used_bytes,
        profiles: selectedProfiles,
      })
    },
    onSuccess: () => {
      invalidate()
      onToast(t('changesSaved'))
      onClose()
    },
    onError: (err) => onError(errMsg(err, t('failedToSaveChanges'))),
  })

  const resetMutation = useMutation({
    mutationFn: () => usersApi.resetTraffic(user!.short_uuid),
    onSuccess: () => {
      invalidate()
      setConfirmReset(false)
      refetch()
      onToast(t('trafficReset'))
    },
    onError: (err) => onError(errMsg(err, t('failedToResetTraffic'))),
  })

  const deleteMutation = useMutation({
    mutationFn: () => usersApi.delete(user!.short_uuid),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users-all'] })
      onToast(t('userDeleted'))
      onDeleted()
    },
    onError: (err) => onError(errMsg(err, t('failedToDeleteUser'))),
  })

  if (!user) return null

  const percent = traffic ? trafficPercent(traffic.used, traffic.limit) : 0
  const busy = saveMutation.isPending || deleteMutation.isPending

  return (
    <Modal open={!!user} onClose={onClose} title={t('editUser')} description={user.name || user.short_uuid} wide>
      <div className="space-y-5">
        <div className="space-y-2.5">
          <SectionLabel>{t('userInformation')}</SectionLabel>
          <div className="bg-bg-tertiary border border-border rounded-lg divide-y divide-border">
            <InfoRow label={t('uuid')}>
              <code className="text-sm font-mono text-accent">{user.short_uuid}</code>
            </InfoRow>
            <InfoRow label={t('name')}>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t('displayName')}
                className="w-48 h-7 bg-bg-secondary border border-border rounded px-2 text-xs text-text-primary
                  placeholder:text-text-muted focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/30 text-right"
              />
            </InfoRow>
            <InfoRow label={t('subscription')}>
              <button
                onClick={() => onCopySubUrl(user)}
                className="inline-flex items-center gap-1.5 text-xs font-medium text-accent hover:text-accent-hover transition-colors cursor-pointer"
                title={buildSubUrl(user.short_uuid)}
              >
                <ClipboardDocumentIcon className="w-3.5 h-3.5" />
                {t('copySubUrl')}
              </button>
            </InfoRow>
          </div>
        </div>

        <div className="space-y-2.5">
          <SectionLabel>{t('trafficSettings')}</SectionLabel>
          {isLoading ? (
            <div className="space-y-3">
              <Skeleton className="h-16 rounded-lg" />
              <Skeleton className="h-2 w-full" />
            </div>
          ) : isError ? (
            <ErrorState message={errMsg(error, t('failedToLoadTraffic'))} onRetry={() => refetch()} />
          ) : traffic ? (
            <>
              <div className="grid grid-cols-3 gap-3">
                <StatBox label={t('used')} value={formatBytes(traffic.used)} />
                <StatBox label={t('limit')} value={traffic.unlimited ? '∞' : formatBytes(traffic.limit)} />
                <StatBox label={t('remaining')} value={traffic.unlimited ? '∞' : formatBytes(traffic.remaining)} />
              </div>
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-xs text-text-muted">
                  <span>{traffic.unlimited ? t('unlimitedPlan') : t('percentUsed', { percent })}</span>
                  {traffic.exceeded && <span className="text-danger font-medium">{t('trafficExceeded')}</span>}
                </div>
                <ProgressBar percent={percent} unlimited={traffic.unlimited} />
              </div>
              <label className="flex items-center gap-2 text-sm text-text-secondary cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={unlimited}
                  onChange={(e) => setUnlimited(e.target.checked)}
                  className="accent-accent w-4 h-4 cursor-pointer"
                />
                {t('unlimitedTraffic')}
              </label>
              {!unlimited && (
                <Input
                  label={t('trafficLimitGb')}
                  type="number"
                  min="0"
                  step="0.1"
                  value={limitGb}
                  onChange={(e) => setLimitGb(e.target.value)}
                  placeholder={t('trafficLimitPlaceholder')}
                />
              )}
            </>
          ) : null}
        </div>

        <div className="space-y-2.5">
          <SectionLabel>{t('timeSettings')}</SectionLabel>
          <Input
            label={t('expiresAt')}
            type="datetime-local"
            value={expiry}
            onChange={(e) => setExpiry(e.target.value)}
          />
        </div>

        <div className="space-y-2.5">
          <SectionLabel>{t('userProfiles')}</SectionLabel>
          <p className="text-xs text-text-muted">{t('userProfilesHint')}</p>
          <ProfileSelector
            profiles={allProfiles}
            loading={profilesLoading}
            selected={selectedProfiles}
            onToggle={toggleProfile}
          />
        </div>

        <div className="border-t border-border pt-4 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            {confirmReset ? (
              <div className="flex items-center gap-2">
                <span className="text-xs text-text-muted">{t('resetUsedTraffic')}</span>
                <Button size="sm" variant="danger" loading={resetMutation.isPending} onClick={() => resetMutation.mutate()}>
                  {t('confirm')}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setConfirmReset(false)}>{t('cancel')}</Button>
              </div>
            ) : (
              <Button size="sm" variant="secondary" disabled={busy || !traffic} onClick={() => setConfirmReset(true)}>
                {t('resetTraffic')}
              </Button>
            )}
            {confirmDelete ? (
              <div className="flex items-center gap-2">
                <span className="text-xs text-text-muted">{t('deleteUserConfirmShort')}</span>
                <Button size="sm" variant="danger" loading={deleteMutation.isPending} onClick={() => deleteMutation.mutate()}>
                  {t('confirm')}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(false)}>{t('cancel')}</Button>
              </div>
            ) : (
              !confirmReset && (
                <Button size="sm" variant="danger" disabled={busy} onClick={() => setConfirmDelete(true)}>
                  <TrashIcon className="w-3.5 h-3.5" />
                  {t('deleteUserAction')}
                </Button>
              )
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={onClose}>{t('cancel')}</Button>
            <Button loading={saveMutation.isPending} disabled={deleteMutation.isPending} onClick={() => saveMutation.mutate()}>
              {t('saveChanges')}
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  )
}

function InfoRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 px-3.5 py-2.5">
      <span className="text-xs text-text-muted">{label}</span>
      {children}
    </div>
  )
}
