/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_DATA_SOURCE?: 'mock' | 'api' | 'ws'
  readonly VITE_WS_URL?: string
  readonly VITE_API_URL?: string
  readonly VITE_AUTH_URL?: string
  readonly VITE_DETECTOR_URL?: string
  readonly VITE_REMEDIATION_URL?: string
  readonly VITE_STRIPE_PUBLISHABLE_KEY?: string
  readonly VITE_CARD_ENTRY?: 'own' | 'elements'
  readonly VITE_PAYPAL_CLIENT_ID?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
