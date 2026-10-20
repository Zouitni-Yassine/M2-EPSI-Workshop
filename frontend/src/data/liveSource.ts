import type { DataSource, Snapshot } from '../types'

/**
 * Source reelle : le moteur de remediation pousse un instantane complet
 * sur le WebSocket a chaque changement. Se reconnecte seule, parce que
 * le conteneur qui l'expose peut lui aussi redemarrer pendant la demo.
 */
export function createLiveSource(url: string): DataSource {
  return {
    subscribe(onSnapshot) {
      let socket: WebSocket | null = null
      let retry: ReturnType<typeof setTimeout> | null = null
      let closed = false

      const connect = () => {
        if (closed) return
        socket = new WebSocket(url)

        socket.onmessage = (ev) => {
          try {
            onSnapshot(JSON.parse(ev.data) as Snapshot)
          } catch {
            // Un message illisible ne doit pas tuer le flux pendant la demo.
          }
        }

        socket.onclose = () => {
          if (closed) return
          retry = setTimeout(connect, 1500)
        }
      }

      connect()

      return () => {
        closed = true
        if (retry) clearTimeout(retry)
        socket?.close()
      }
    },
  }
}
