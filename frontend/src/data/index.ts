import type { DataSource } from '../types'
import { createLiveSource } from './liveSource'
import { createMockSource } from './mockSource'

/** Un seul point de bascule entre la maquette et le backend. */
export function createDataSource(): DataSource {
  const mode = import.meta.env.VITE_DATA_SOURCE ?? 'mock'
  if (mode === 'live') {
    return createLiveSource(import.meta.env.VITE_WS_URL ?? 'ws://localhost:8080/ws/state')
  }
  return createMockSource()
}
