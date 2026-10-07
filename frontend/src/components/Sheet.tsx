import { X } from 'lucide-react'
import { useEffect, useId, useRef } from 'react'
import type { ReactNode } from 'react'

/** Bottom sheet on glass. Keyboard operable: Escape closes, Tab stays inside, and
 *  focus returns to whatever opened it. */
export function Sheet({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
}) {
  const panel = useRef<HTMLDivElement>(null)
  const opener = useRef<Element | null>(null)
  const titleId = useId()

  useEffect(() => {
    if (!open) return
    opener.current = document.activeElement
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const focusables = () =>
      Array.from(
        panel.current?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      )

    focusables()[0]?.focus()

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== 'Tab') return
      const items = focusables()
      if (items.length === 0) return
      const first = items[0]
      const last = items[items.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previousOverflow
      ;(opener.current as HTMLElement | null)?.focus?.()
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center">
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="fade-enter absolute inset-0 bg-abyss/70 backdrop-blur-sm"
      />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="sheet-enter sheet-panel relative w-full max-w-home rounded-t-sheet px-screen pt-[22px] pb-[max(28px,env(safe-area-inset-bottom))]"
      >
        <div className="mb-5 flex items-center justify-between gap-3">
          <h2 id={titleId} className="text-lg font-bold">
            {title}
          </h2>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="-mr-2 grid size-tap place-items-center rounded-full text-fog transition-colors hover:text-mist"
          >
            <X aria-hidden="true" size={18} strokeWidth={2} />
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}
