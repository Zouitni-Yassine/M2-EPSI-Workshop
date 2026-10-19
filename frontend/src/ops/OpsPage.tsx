import { useEffect, useState } from 'react'
import { createDataSource } from '../data'
import type { Snapshot } from '../types'
import { AnomalyChart } from '../components/AnomalyChart'
import { CanaryRibbon } from '../components/CanaryRibbon'
import { MetricsRow } from '../components/MetricsRow'
import { ServiceGrid } from '../components/ServiceGrid'
import { StatusBand } from '../components/StatusBand'
import { Timeline } from '../components/Timeline'

export function OpsPage() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)

  useEffect(() => createDataSource().subscribe(setSnapshot), [])

  if (!snapshot) {
    return (
      <main className="mx-auto max-w-[1200px] px-6 py-24 text-center text-sm text-text-2">
        Connexion au moteur de remédiation…
      </main>
    )
  }

  return (
    <main data-state={snapshot.state} className="mx-auto grid max-w-[1200px] gap-5 px-6 py-8 lg:grid-cols-12">
      <div className="lg:col-span-12">
        <StatusBand
          state={snapshot.state}
          elapsed={snapshot.elapsed}
          humanActions={snapshot.humanActions}
        />
      </div>

      <div className="lg:col-span-12">
        <CanaryRibbon ticks={snapshot.canary} />
      </div>

      <div className="flex flex-col gap-5 lg:col-span-8">
        <AnomalyChart points={snapshot.anomaly} threshold={snapshot.threshold} detector={snapshot.detector} />
        <ServiceGrid services={snapshot.services} />
        <MetricsRow metrics={snapshot.metrics} />
      </div>

      <div className="lg:col-span-4">
        <Timeline events={snapshot.events} />
      </div>
    </main>
  )
}
