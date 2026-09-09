import { useState, useEffect, type ReactNode } from 'react'
import { useLanguage, type SupportedLanguage } from './i18n/useLanguage'
import {
  ArrowDownTrayIcon,
  LinkIcon,
  ClipboardDocumentIcon,
  LightBulbIcon,
  CheckCircleIcon,
  NoSymbolIcon,
  ChevronDownIcon,
  MagnifyingGlassIcon,
  ExclamationTriangleIcon,
} from '@heroicons/react/24/outline'
import AndroidSvg from './assets/icons/android.svg?react'
import WindowsSvg from './assets/icons/windows.svg?react'
import LinuxSvg from './assets/icons/linux.svg?react'

function isIOS(): boolean {
  if (typeof navigator === 'undefined') return false
  return /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
}

function useIOSCheck() {
  const [detected, setDetected] = useState(false)
  useEffect(() => { setDetected(isIOS()) }, [])
  return detected
}

type Platform = 'android' | 'windows' | 'linux'

function detectPlatform(): Platform | null {
  if (typeof navigator === 'undefined') return null
  const ua = navigator.userAgent.toLowerCase()
  if (/android/.test(ua)) return 'android'
  if (/win/.test(ua)) return 'windows'
  if (/linux/.test(ua)) return 'linux'
  if (/mac/.test(ua)) return 'linux'
  return null
}

function usePlatform() {
  const [platform, setPlatform] = useState<Platform | null>(null)
  useEffect(() => { setPlatform(detectPlatform()) }, [])
  return platform
}

function useToast() {
  const [message, setMessage] = useState<string | null>(null)
  const timerRef = useState(() => ({ current: undefined as ReturnType<typeof setTimeout> | undefined }))[0]

  useEffect(() => () => { clearTimeout(timerRef.current) }, [])

  const show = (msg: string) => {
    clearTimeout(timerRef.current)
    setMessage(msg)
    timerRef.current = setTimeout(() => setMessage(null), 2500)
  }
  return { message, show }
}

function useCurrentUrl() {
  const [url, setUrl] = useState('')
  useEffect(() => { setUrl(window.location.href) }, [])
  return url
}

function useSubId(): string | null {
  if (typeof window === 'undefined') return null
  const match = window.location.pathname.match(/^\/([^/]+)/)
  return match ? match[1] : null
}
type CheckStatus = 'loading' | 'exists' | 'not_found'

function useSubscriptionCheck(): {
  status: CheckStatus
  providerName: string | null
  networkError: boolean
} {
  const subId = useSubId()
  const [status, setStatus] = useState<CheckStatus>(() => subId ? 'loading' : 'not_found')
  const [providerName, setProviderName] = useState<string | null>(null)
  const [networkError, setNetworkError] = useState(false)

  useEffect(() => {
    if (!subId) {
      setStatus('not_found')
      setNetworkError(false)
      return
    }

    setStatus('loading')
    setProviderName(null)
    setNetworkError(false)

    fetch(`/${subId}/check`)
      .then((r) => {
        if (r.status === 404) {
          setStatus('not_found')
          return null
        }
        if (!r.ok) {
          setStatus('not_found')
          return null
        }
        return r.text()
      })
      .then((text) => {
        if (text === null) return
        if (!text.trim()) {
          setStatus('not_found')
          return
        }
        setProviderName(text)
        setStatus('exists')
      })
      .catch(() => {
        setStatus('not_found')
        setNetworkError(true)
      })
  }, [subId])

  return { status, providerName, networkError }
}

export default function App() {
  const ios = useIOSCheck()
  const toast = useToast()
  const currentUrl = useCurrentUrl()
  const { status, providerName, networkError } = useSubscriptionCheck()
  const [showMain, setShowMain] = useState(false)

  if (ios && !showMain) {
    return <IosOverlay onShowMain={() => setShowMain(true)} />
  }

  if (status === 'loading') {
    return <LoadingScreen />
  }

  if (status === 'not_found') {
    return <NotFoundScreen networkError={networkError} />
  }

  return (
    <div className="min-h-screen">
      <LanguageSwitcher />
      <Hero providerName={providerName} />
      <main className="max-w-3xl mx-auto px-5 pb-16 space-y-6">
        <DownloadSection />
        <SubscribeSection url={currentUrl} showToast={toast.show} />
        <TipsSection />
      </main>
      <Footer />
      <Toast message={toast.message} />
    </div>
  )
}

/* ─── Language Switcher ─── */

function LanguageSwitcher() {
  const { language, setLanguage } = useLanguage()
  const langs: SupportedLanguage[] = ['en', 'ru']

  return (
    <div className="fixed top-4 right-4 z-40 flex rounded-lg bg-bg-secondary border border-border shadow-soft overflow-hidden">
      {langs.map((lang) => (
        <button
          key={lang}
          onClick={() => setLanguage(lang)}
          className={`px-3 h-8 text-xs font-semibold transition-colors cursor-pointer
            ${language === lang
              ? 'bg-accent text-white'
              : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover'}`}
        >
          {lang.toUpperCase()}
        </button>
      ))}
    </div>
  )
}

/* ─── Loading Screen ─── */

function LoadingScreen() {
  const { t } = useLanguage()
  return (
    <div className="fixed inset-0 flex items-center justify-center bg-bg-primary">
      <div className="flex flex-col items-center gap-4 animate-fade-in">
        <div className="w-8 h-8 border-2 border-border border-t-accent rounded-full animate-spin" />
        <p className="text-sm text-text-muted">{t('checking')}</p>
      </div>
    </div>
  )
}

/* ─── iOS Overlay ─── */

function IosOverlay({ onShowMain }: { onShowMain: () => void }) {
  const { t } = useLanguage()
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-primary">
      <div className="absolute inset-0 pointer-events-none"
        style={{
          background:
            'radial-gradient(1200px 600px at 100% -10%, rgba(99, 102, 241, 0.08), transparent 60%)',
        }}
      />
      <div className="relative z-10 max-w-sm w-full mx-5 animate-scale-in">
        <div className="bg-bg-secondary border border-border rounded-xl shadow-elevated p-8 text-center space-y-5">
          <div className="flex items-center justify-center w-16 h-16 mx-auto rounded-full bg-danger/10">
            <NoSymbolIcon className="w-8 h-8 text-danger" />
          </div>
          <div className="space-y-2">
            <h2 className="text-xl font-bold text-text-primary">{t('iosTitle')}</h2>
            <p className="text-sm text-text-secondary leading-relaxed">{t('iosDesc')}</p>
          </div>
          <button
            onClick={onShowMain}
            className="w-full h-11 rounded-lg font-medium text-sm bg-bg-tertiary border border-border
              text-text-secondary hover:text-text-primary hover:bg-bg-hover hover:border-border-light
              transition-all duration-150 cursor-pointer active:scale-[0.98]"
          >
            {t('iosButton')}
          </button>
        </div>
      </div>
    </div>
  )
}

/* ─── Not Found Screen ─── */

function NotFoundScreen({ networkError }: { networkError: boolean }) {
  const { t } = useLanguage()
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-primary">
      <div className="absolute inset-0 pointer-events-none"
        style={{
          background:
            'radial-gradient(1200px 600px at 100% -10%, rgba(99, 102, 241, 0.08), transparent 60%)',
        }}
      />
      <div className="relative z-10 max-w-sm w-full mx-5 animate-scale-in">
        <div className="bg-bg-secondary border border-border rounded-xl shadow-elevated p-8 text-center space-y-5">
          <div className="flex items-center justify-center w-16 h-16 mx-auto rounded-full"
            style={{ backgroundColor: networkError ? 'rgba(248, 81, 73, 0.1)' : 'rgba(210, 153, 34, 0.1)' }}>
            {networkError
              ? <ExclamationTriangleIcon className="w-8 h-8 text-danger" />
              : <MagnifyingGlassIcon className="w-8 h-8 text-warning" />
            }
          </div>
          <div className="space-y-2">
            <h2 className="text-xl font-bold text-text-primary">
              {networkError ? t('networkErrorTitle') : t('notFoundTitle')}
            </h2>
            <p className="text-sm text-text-secondary leading-relaxed">
              {networkError ? t('networkErrorDesc') : t('notFoundDesc')}
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

/* ─── Toast ─── */

function Toast({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 animate-toast-in">
      <div className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-success/15 border border-success/30
        text-sm font-medium text-success shadow-elevated backdrop-blur-sm">
        <CheckCircleIcon className="w-4 h-4 shrink-0" />
        {message}
      </div>
    </div>
  )
}

/* ─── Hero ─── */

function Hero({ providerName }: { providerName: string | null }) {
  const { t } = useLanguage()
  return (
    <header className="relative overflow-hidden">
      <div className="absolute inset-0 pointer-events-none"
        style={{
          background:
            'radial-gradient(800px 400px at 50% 0%, rgba(88, 166, 255, 0.06), transparent 70%)',
        }}
      />
      <div className="relative max-w-3xl mx-auto px-5 pt-14 pb-10 text-center space-y-5 animate-fade-in">
        <div className="flex items-center justify-center w-14 h-14 mx-auto rounded-2xl bg-accent/10 shadow-glow">
          <WavesIcon className="w-7 h-7 text-accent" />
        </div>
        <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-text-primary">
          {providerName || 'OLCWave'}
        </h1>
        <p className="text-base sm:text-lg text-text-secondary leading-relaxed max-w-lg mx-auto">
          {t('heroSubtitle')}
        </p>
      </div>
    </header>
  )
}

/* ─── Download Section ─── */

const RELEASE_PAGE = 'https://github.com/alananisimov/olcbox/releases/tag/nightly'
const RELEASE_API = 'https://api.github.com/repos/alananisimov/olcbox/releases/tags/nightly'

const PLATFORMS: { key: Platform }[] = [
  { key: 'android' },
  { key: 'windows' },
  { key: 'linux' },
]

type GitHubAsset = { name: string; browser_download_url: string }
type GitHubRelease = { assets?: GitHubAsset[] }
type DownloadUrls = Record<Platform, string>

const FALLBACK_DOWNLOADS: DownloadUrls = {
  android: RELEASE_PAGE,
  windows: RELEASE_PAGE,
  linux: RELEASE_PAGE,
}

const DOWNLOAD_CACHE_KEY = 'olcbox-nightly-downloads'
const DOWNLOAD_CACHE_TTL = 6 * 60 * 60 * 1000

async function getOlcboxDownloads(): Promise<DownloadUrls> {
  try {
    const cached = localStorage.getItem(DOWNLOAD_CACHE_KEY)
    if (cached) {
      const parsed = JSON.parse(cached) as { timestamp: number; urls: DownloadUrls }
      if (Date.now() - parsed.timestamp < DOWNLOAD_CACHE_TTL) return parsed.urls
    }

    const response = await fetch(RELEASE_API, { headers: { Accept: 'application/vnd.github+json' } })
    if (!response.ok) throw new Error(`GitHub API returned ${response.status}`)

    const release: GitHubRelease = await response.json()
    const assets = release.assets ?? []

    const findAsset = (pattern: RegExp) =>
      assets.find((a) => pattern.test(a.name))?.browser_download_url

    const urls: DownloadUrls = {
      android: findAsset(/android-release\.apk$/i) ?? findAsset(/android.*\.apk$/i) ?? RELEASE_PAGE,
      windows: findAsset(/windows-amd64\.exe$/i) ?? findAsset(/windows.*\.exe$/i) ?? RELEASE_PAGE,
      linux: findAsset(/linux-amd64\.appimage$/i) ?? findAsset(/linux.*\.appimage$/i) ?? RELEASE_PAGE,
    }

    localStorage.setItem(DOWNLOAD_CACHE_KEY, JSON.stringify({ timestamp: Date.now(), urls }))
    return urls
  } catch (error) {
    console.error('Failed to load OLCBox downloads:', error)
    return FALLBACK_DOWNLOADS
  }
}

const PLATFORM_ICONS: Record<Platform, ReactNode> = {
  android: <AndroidIcon className="w-5 h-5" />,
  windows: <WindowsIcon className="w-5 h-5" />,
  linux: <LinuxIcon className="w-5 h-5" />,
}

function DownloadSection() {
  const { t } = useLanguage()
  const detected = usePlatform()
  const [selected, setSelected] = useState<Platform>(detected ?? 'android')
  const [downloadUrls, setDownloadUrls] = useState<DownloadUrls>(FALLBACK_DOWNLOADS)

  useEffect(() => { if (detected) setSelected(detected) }, [detected])

  useEffect(() => {
    let cancelled = false
    getOlcboxDownloads().then((urls) => { if (!cancelled) setDownloadUrls(urls) })
    return () => { cancelled = true }
  }, [])

  return (
    <Section title={t('downloadTitle')} icon={<ArrowDownTrayIcon className="w-4 h-4" />}>
      <div className="space-y-4">
        <p className="text-sm text-text-secondary leading-relaxed">
          {t('downloadDesc')}
        </p>

        <div className="flex items-center gap-3">
          <div className="relative">
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value as Platform)}
              className="appearance-none h-11 pl-10 pr-8 rounded-lg bg-bg-tertiary border border-border
                text-sm font-medium text-text-primary cursor-pointer
                hover:border-border-light focus:outline-none focus:border-accent/50 transition-colors"
            >
              {PLATFORMS.map((p) => (
                <option key={p.key} value={p.key}>{t(p.key)}</option>
              ))}
            </select>
            <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-accent">
              {PLATFORM_ICONS[selected]}
            </span>
            <ChevronDownIcon className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" />
          </div>

          <a
            href={downloadUrls[selected]}
            target="_blank"
            rel="noopener noreferrer"
            className="flex-1 h-11 flex items-center justify-center gap-2 rounded-lg font-medium text-sm
              bg-accent text-white shadow-soft hover:bg-accent-hover
              transition-all duration-150 no-underline active:scale-[0.98]"
          >
            <ArrowDownTrayIcon className="w-4 h-4" />
            {t('download')}
          </a>
        </div>

        <p className="text-xs text-text-muted">
          {t('iosComingSoon')}
        </p>
      </div>
    </Section>
  )
}

/* ─── Subscribe Section ─── */

function SubscribeSection({ url, showToast }: { url: string; showToast: (msg: string) => void }) {
  const { t } = useLanguage()
  const copyUrl = () => {
    navigator.clipboard.writeText(url).then(() => showToast(t('linkCopied')))
  }

  return (
    <Section title={t('subscribeTitle')} icon={<LinkIcon className="w-4 h-4" />}>
      <div className="space-y-4">
        <p className="text-sm text-text-secondary leading-relaxed">
          {t('subscribeDesc')}
        </p>

        <Step number={1} title={t('step1')} />
        <Step number={2} title={t('step2')} />
        <Step number={3} title={t('step3')} />

        <div className="bg-bg-tertiary border border-border rounded-xl p-4 space-y-3">
          <p className="text-xs font-medium text-text-muted uppercase tracking-wider">{t('yourLink')}</p>
          <div className="flex items-center gap-2">
            <code className="flex-1 text-xs text-accent font-mono break-all leading-relaxed bg-bg-primary/50
              rounded-lg px-3 py-2.5 border border-border">
              {url || t('loading')}
            </code>
            <button
              onClick={copyUrl}
              disabled={!url}
              className="shrink-0 h-10 px-3.5 rounded-lg text-xs font-medium
                bg-accent text-white shadow-soft hover:bg-accent-hover
                transition-all duration-150 cursor-pointer active:scale-[0.98]
                disabled:opacity-40 disabled:pointer-events-none
                flex items-center gap-1.5"
            >
              <ClipboardDocumentIcon className="w-3.5 h-3.5" />
              {t('copy')}
            </button>
          </div>
          <p className="text-xs text-text-muted">
            {t('copyHint')}
          </p>
        </div>
      </div>
    </Section>
  )
}

/* ─── Tips Section ─── */

function TipsSection() {
  const { t } = useLanguage()
  return (
    <Section title={t('tipsTitle')} icon={<LightBulbIcon className="w-4 h-4" />}>
      <div className="space-y-3">
        <Tip
          title={t('tipSubNotLoading')}
          text={t('tipSubNotLoadingText')}
        />
        <Tip
          title={t('tipSlow')}
          text={t('tipSlowText')}
        />
        <Tip
          title={t('tipExpired')}
          text={t('tipExpiredText')}
        />
        <Tip
          title={t('tipHelp')}
          text={t('tipHelpText')}
        />
      </div>
    </Section>
  )
}

/* ─── Footer ─── */

function Footer() {
  return (
    <footer className="border-t border-border">
      <div className="max-w-3xl mx-auto px-5 py-8 text-center space-y-2">
        <div className="flex items-center justify-center gap-2 text-text-muted">
          <WavesIcon className="w-4 h-4" />
          <span className="text-xs font-medium">OLCWave</span>
        </div>
        <a
          href="https://github.com/invdevv/olcwave"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 text-xs text-text-muted hover:text-text-primary transition-colors"
        >
          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/>
          </svg>
          GitHub
        </a>
      </div>
    </footer>
  )
}

/* ─── Shared building blocks ─── */

function Section({
  title,
  icon,
  children,
}: {
  title: string
  icon?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="bg-bg-secondary border border-border rounded-xl shadow-soft overflow-hidden animate-fade-in">
      <div className="px-5 py-3.5 border-b border-border flex items-center gap-2">
        {icon && <span className="text-text-muted">{icon}</span>}
        <h2 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">{title}</h2>
      </div>
      <div className="p-5">
        {children}
      </div>
    </section>
  )
}

function Step({ number, title }: { number: number; title: string }) {
  return (
    <div className="flex items-center gap-3">
      <div className="flex items-center justify-center w-7 h-7 rounded-full bg-accent/10 text-accent
        text-xs font-bold shrink-0">
        {number}
      </div>
      <p className="text-sm text-text-primary">{title}</p>
    </div>
  )
}

function Tip({ title, text }: { title: string; text: string }) {
  return (
    <div className="p-3.5 rounded-lg bg-bg-tertiary border border-border">
      <p className="text-sm font-medium text-text-primary">{title}</p>
      <p className="text-xs text-text-secondary mt-1 leading-relaxed">{text}</p>
    </div>
  )
}

/* ─── Icons ─── */

function WavesIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M3 8c1.5 0 2.5-1.5 4.5-1.5S10.5 8 12 8s3-1.5 5-1.5S19.5 8 21 8M3 12c1.5 0 2.5-1.5 4.5-1.5S10.5 12 12 12s3-1.5 5-1.5S19.5 12 21 12M3 16c1.5 0 2.5-1.5 4.5-1.5S10.5 16 12 16s3-1.5 5-1.5S19.5 16 21 16" />
    </svg>
  )
}

function AndroidIcon({ className }: { className?: string }) {
  return <AndroidSvg className={className} />
}

function WindowsIcon({ className }: { className?: string }) {
  return <WindowsSvg className={className} />
}

function LinuxIcon({ className }: { className?: string }) {
  return <LinuxSvg className={className} />
}
