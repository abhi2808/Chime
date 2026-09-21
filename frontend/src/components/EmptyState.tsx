import type { ReactNode } from 'react'

export function EmptyState({
  title,
  body,
  icon,
  action,
}: {
  title: string
  body?: string
  icon?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="glass flex flex-col items-center gap-3 rounded-sheet px-screen py-10 text-center">
      {icon ? <div className="text-fog">{icon}</div> : null}
      <h2 className="text-headline">{title}</h2>
      {body ? <p className="text-body max-w-[46ch] text-fog">{body}</p> : null}
      {action}
    </div>
  )
}
