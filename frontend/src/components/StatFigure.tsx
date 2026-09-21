/** One WHOOP number with an honest label, e.g. "Recovery 41%". */
export function StatFigure({
  label,
  value,
  hint,
}: {
  label: string
  value: string
  hint?: string
}) {
  return (
    <div className="flex flex-col">
      <span className="text-caption text-fog">{label}</span>
      <span className="text-headline">{value}</span>
      {hint ? <span className="text-caption text-fog">{hint}</span> : null}
    </div>
  )
}
