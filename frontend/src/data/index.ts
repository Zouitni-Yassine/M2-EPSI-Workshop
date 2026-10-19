import type { DataSource } from '../types'
import { createApiSource } from './apiSource'
import { createLiveSource } from './liveSource'
import { createMockSource } from './mockSource'

/**
 * Un seul point de bascule pour la supervision :
 *   mock — scénario rejoué en boucle, pour développer et répéter
 *   api  — payment-api et Stripe sondés en direct, sans moteur de remédiation
 *   ws   — le moteur de remédiation pousse l'état complet sur un WebSocket
 */
export function createDataSource(): DataSource {
  const mode = import.meta.env.VITE_DATA_SOURCE ?? 'mock'
  if (mode === 'ws') {
    return createLiveSource(import.meta.env.VITE_WS_URL ?? 'ws://localhost:8080/ws/state')
  }
  if (mode === 'api') {
    return createApiSource(import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api')
  }
  return createMockSource()
}
