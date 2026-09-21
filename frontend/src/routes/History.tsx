import { EmptyState } from '../components/EmptyState'

export function History() {
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-title">History</h1>
      <EmptyState title="No sessions yet" body="Chime in and they will show up here." />
    </div>
  )
}
