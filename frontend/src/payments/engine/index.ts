import type { PaymentEngine } from '../domain/types'
import { createApiEngine } from './apiEngine'
import { createLocalEngine } from './localEngine'

let engine: PaymentEngine | null = null

/** Un seul moteur par session, pour que le journal et le solde persistent. */
export function paymentEngine(): PaymentEngine {
  if (engine) return engine
  engine =
    import.meta.env.VITE_DATA_SOURCE === 'live'
      ? createApiEngine(import.meta.env.VITE_API_URL ?? 'http://192.168.137.1:8080/api')
      : createLocalEngine()
  return engine
}
