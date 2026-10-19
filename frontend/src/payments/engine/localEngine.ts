import { DECLINE_MESSAGE, outcomeFor } from '../domain/testCards'
import { timeNow } from '../domain/money'
import type {
  Balance,
  Cents,
  DeclineCode,
  OnStep,
  PaymentEngine,
  PaymentIntent,
  Rail,
} from '../domain/types'

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))

const EMPTY_RAIL: Rail = {
  authorization: 'pending',
  authentication: 'pending',
  capture: 'pending',
  settlement: 'pending',
}

function id(prefix: string): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 12)}`
}

function reference(): string {
  const n = Math.floor(Math.random() * 1e8)
    .toString()
    .padStart(8, '0')
  return `RSL-${n.slice(0, 4)}-${n.slice(4)}`
}

/**
 * Reproduit la sémantique de Stripe sans réseau : mêmes cartes de test,
 * mêmes transitions, mêmes codes de refus. C'est le filet de sécurité si le
 * backend ou Internet manque pendant la démonstration.
 */
export function createLocalEngine(): PaymentEngine {
  const store = new Map<string, PaymentIntent>()
  let available: Cents = 1_284_050

  const log = (i: PaymentIntent, note: string): PaymentIntent => ({
    ...i,
    history: [...i.history, { at: timeNow(), status: i.status, note }],
  })

  const save = (i: PaymentIntent, onStep?: OnStep): PaymentIntent => {
    store.set(i.id, i)
    onStep?.(i)
    return i
  }

  const fail = (i: PaymentIntent, stage: keyof Rail, code: DeclineCode, onStep?: OnStep) => {
    const failed: PaymentIntent = {
      ...i,
      status: 'canceled',
      error: { code, message: DECLINE_MESSAGE[code] },
      rail: { ...i.rail, [stage]: 'failed' },
    }
    return save(log(failed, `Refus réseau — ${code}`), onStep)
  }

  /** Capture puis compensation : le tronc commun après toute autorisation réussie. */
  const settle = async (i: PaymentIntent, onStep?: OnStep): Promise<PaymentIntent> => {
    i = save({ ...i, status: 'processing', rail: { ...i.rail, capture: 'active' } }, onStep)
    await wait(700)
    i = save(
      log({ ...i, rail: { ...i.rail, capture: 'done', settlement: 'active' } }, 'Fonds capturés'),
      onStep,
    )
    await wait(600)
    available += i.amount
    return save(
      log(
        { ...i, status: 'succeeded', rail: { ...i.rail, settlement: 'done' } },
        'Compensation effectuée',
      ),
      onStep,
    )
  }

  return {
    provider: 'local',

    async createIntent(amount, card) {
      const intent: PaymentIntent = {
        id: id('pi'),
        idempotencyKey: id('idem'),
        amount,
        currency: 'EUR',
        status: 'requires_confirmation',
        card,
        createdAt: new Date().toISOString(),
        reference: reference(),
        rail: { ...EMPTY_RAIL },
        history: [
          { at: timeNow(), status: 'requires_confirmation', note: 'Intention de paiement créée' },
        ],
      }
      store.set(intent.id, intent)
      return intent
    },

    async confirm(intentId, source, onStep) {
      if (source.kind !== 'raw') {
        throw new Error('Le moteur local attend les chiffres de la carte.')
      }
      let i = store.get(intentId)
      if (!i) throw new Error(`Intention inconnue : ${intentId}`)

      i = save({ ...i, status: 'processing', rail: { ...i.rail, authorization: 'active' } }, onStep)
      await wait(900)

      const outcome = outcomeFor(source.card.number)

      if (outcome.kind === 'decline') {
        return fail(i, 'authorization', outcome.code, onStep)
      }

      if (outcome.kind === 'challenge') {
        return save(
          log(
            {
              ...i,
              status: 'requires_action',
              rail: { ...i.rail, authorization: 'done', authentication: 'active' },
            },
            'L’émetteur exige une authentification forte',
          ),
          onStep,
        )
      }

      i = save(
        log(
          { ...i, rail: { ...i.rail, authorization: 'done', authentication: 'skipped' } },
          'Autorisation accordée',
        ),
        onStep,
      )
      return settle(i, onStep)
    },

    async authenticate(intentId, code, onStep) {
      let i = store.get(intentId)
      if (!i) throw new Error(`Intention inconnue : ${intentId}`)

      await wait(650)
      if (code.replace(/\D/g, '') !== '1234') {
        return fail(i, 'authentication', 'authentication_failed', onStep)
      }

      i = save(
        log(
          { ...i, status: 'processing', rail: { ...i.rail, authentication: 'done' } },
          'Authentification validée par l’émetteur',
        ),
        onStep,
      )
      return settle(i, onStep)
    },

    async list() {
      return [...store.values()].sort((a, b) => b.createdAt.localeCompare(a.createdAt))
    },

    async balance(): Promise<Balance> {
      const next = new Date()
      next.setDate(next.getDate() + 1)
      next.setHours(9, 0, 0, 0)
      return { available, pending: 0, nextPayoutAt: next.toISOString() }
    },
  }
}
