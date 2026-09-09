const translations = {
  heroSubtitle: 'Fast, secure and easy-to-use proxy service. Set up in two simple steps.',

  downloadTitle: 'Download OLCBox',
  download: 'Download',
  downloadDesc: 'OLCBox is client application for connecting to OLCRTC. Download and install it on your device.',
  android: 'Android',
  androidDesc: 'APK direct download',
  windows: 'Windows',
  windowsDesc: '.exe installer',
  linux: 'Linux',
  linuxDesc: '.AppImage',
  iosComingSoon: 'iOS support is coming soon. Check back later for updates.',

  subscribeTitle: 'Add subscription',
  subscribeDesc: 'After installing OLCBox, add your subscription link to automatically configure all servers.',
  step1: 'Open OLCBox',
  step2: 'Tap "+" - "Enter link or URI"',
  step3: 'Paste the subscription URL',
  yourLink: 'Your subscription link',
  copy: 'Copy',
  linkCopied: 'Link copied',
  copyHint: 'Copy this link and paste it into OLCBox when adding a subscription.',
  loading: 'Loading...',

  tipsTitle: 'Quick tips',
  tipSubNotLoading: 'Subscription not loading?',
  tipSubNotLoadingText: 'Make sure you have an active internet connection and that the URL is copied correctly. Try pasting the link directly instead of typing it.',
  tipSlow: 'Connection is slow?',
  tipSlowText: 'Try switching to a different server location in OLCBox. Some servers may be faster depending on your region.',
  tipExpired: 'App says "expired"?',
  tipExpiredText: 'Your subscription may have expired. Contact the administrator to renew your access.',
  tipHelp: 'Need help?',
  tipHelpText: 'Reach out to your service administrator for account-related questions and support.',

  iosTitle: 'iOS is not supported yet',
  iosDesc: 'OLCBox is currently available for Android and Desktop platforms. iOS support is planned for a future release.',
  iosButton: 'View setup instructions anyway',

  checking: 'Checking subscription...',
  notFoundTitle: 'Subscription not found',
  notFoundDesc: 'The link may be outdated or has been deleted.',
  networkErrorTitle: 'Network error',
  networkErrorDesc: 'Check your internet connection and try again.',

  langEn: 'EN',
  langRu: 'RU',
}

export type TranslationKey = keyof typeof translations
export type Translation = Record<TranslationKey, string>

const en: Translation = translations
export default en
