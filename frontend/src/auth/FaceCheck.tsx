import { useEffect, useRef } from 'react'
import type { Pose } from './faceGuide'
import { FaceScanner, type ScanStep } from './FaceScanner'
import { probeFace, sendFaceFrames, type FaceResult } from './session'

const STEPS: ScanStep[] = [{ pose: 'face', title: 'Reconnaissance faciale' }]

/**
 * Juste après l'identifiant d'un compte du back-office : la caméra s'allume et suit le visage ;
 * dès qu'il est bien placé, de face, quelques images partent au jugement du serveur, puis elle
 * s'éteint, quel que soit le résultat.
 */
export function FaceCheck({
  challenge,
  frames,
  onResult,
  onError,
}: {
  challenge: string
  frames: number
  onResult: (result: FaceResult) => void
  onError: (error: unknown) => void
}) {
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  async function check(shots: Record<Pose, Blob[]>) {
    try {
      const result = await sendFaceFrames(challenge, shots.face)
      if (alive.current) onResult(result)
    } catch (err) {
      if (alive.current) onError(err)
    }
  }

  return (
    <div className="rise">
      <FaceScanner
        key={challenge}
        steps={STEPS}
        shots={Math.min(Math.max(frames, 2), 8)}
        probe={(frame) => probeFace(challenge, frame)}
        onComplete={(shots) => void check(shots)}
        onError={(err) => {
          if (alive.current) onError(err)
        }}
        doneLabel="Vérification du visage…"
      />
    </div>
  )
}
