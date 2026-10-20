export function Wordmark({ light = false }: { light?: boolean }) {
  return (
    <span className={`font-logo text-2xl font-bold tracking-tight ${light ? 'text-white' : 'text-logo'}`}>
      YAZNOW
    </span>
  )
}
