export function Wordmark() {
  return (
    <span className="flex items-center gap-2">
      <span className="grid size-7 place-items-center rounded-md bg-accent text-white">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
          <path d="M2 7h10M7 2v10" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
        </svg>
      </span>
      <span className="text-[15px] font-semibold tracking-tight">Resilience Pay</span>
    </span>
  )
}
