import {
  INSTANCE_LOADING_STATE,
  PayPalOneTimePaymentButton,
  usePayPal,
} from '@paypal/react-paypal-js/sdk-v6'

interface Props {
  /** Crée la commande côté backend ; renvoie son identifiant au SDK. */
  onCreate: () => Promise<{ orderId: string }>
  /** Le payeur a validé dans la fenêtre PayPal : on capture. */
  onApprove: (orderId: string) => Promise<void>
  onCancel: () => void
  onError: (message: string) => void
  error?: string
  disabled: boolean
}

/**
 * Le bouton PayPal du SDK v6, dans un panneau au style du tunnel. Doit être
 * rendu sous un `PayPalProvider` (voir PayPage).
 */
export function PayPalPanel({ onCreate, onApprove, onCancel, onError, error, disabled }: Props) {
  const { loadingStatus, error: sdkError } = usePayPal()

  return (
    <div className="rounded-panel border border-edge bg-card shadow-panel">
      <div className="flex items-start justify-between gap-4 border-b border-edge px-6 py-4">
        <div>
          <h2 className="text-base font-semibold">Payer avec PayPal</h2>
          <p className="mt-0.5 text-sm text-text-2">Connexion avec un compte acheteur sandbox.</p>
        </div>
        <span className="shrink-0 rounded-md bg-well px-2 py-1 text-[11px] font-semibold text-text-2">
          PayPal · sandbox
        </span>
      </div>

      <div className="px-6 py-5">
        {error ? (
          <p className="rise mb-3 rounded-lg border border-bad/30 bg-bad/5 px-3.5 py-2.5 text-sm text-bad">{error}</p>
        ) : null}

        {loadingStatus === INSTANCE_LOADING_STATE.PENDING ? (
          <div className="h-12 animate-pulse rounded-lg bg-well" aria-label="Chargement de PayPal" />
        ) : loadingStatus === INSTANCE_LOADING_STATE.REJECTED ? (
          <p className="rounded-lg border border-note/30 bg-note/10 px-3.5 py-2.5 text-sm text-note">
            PayPal n’a pas pu être chargé ({sdkError?.message ?? 'SDK indisponible'}). Le paiement par carte reste
            possible.
          </p>
        ) : (
          <PayPalOneTimePaymentButton
            type="pay"
            disabled={disabled}
            createOrder={onCreate}
            onApprove={({ orderId }) => onApprove(orderId)}
            onCancel={onCancel}
            onError={(err) => onError(err.message || 'PayPal a rencontré une erreur.')}
          />
        )}
      </div>
    </div>
  )
}
