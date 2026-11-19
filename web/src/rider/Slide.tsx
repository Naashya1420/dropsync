import { useRef, useState } from 'react'
import { IcArrow } from './icons'

/** Slide-to-confirm, styled like the partner app's green action bar with a black
 *  round knob. Drag the knob to the end; Enter/Space also confirms (accessible). */
export default function Slide({ label, onDone, disabled }: { label: string; onDone: () => void; disabled?: boolean }) {
  const track = useRef<HTMLDivElement>(null)
  const [x, setX] = useState(0)
  const [drag, setDrag] = useState<number | null>(null)
  const KNOB = 48

  const max = () => (track.current ? track.current.clientWidth - KNOB - 8 : 200)
  const fire = () => {
    setX(max())
    setTimeout(() => { onDone(); setX(0) }, 160)
  }
  return (
    <div
      ref={track}
      className={`zslide ${disabled ? 'disabled' : ''}`}
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-label={label}
      aria-disabled={disabled}
      onKeyDown={(e) => { if (!disabled && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); fire() } }}
      onPointerMove={(e) => { if (drag != null && !disabled) setX(Math.max(0, Math.min(max(), e.clientX - drag))) }}
      onPointerUp={() => {
        if (drag == null) return
        setDrag(null)
        if (x >= max() * 0.85) fire()
        else setX(0)
      }}
      onPointerCancel={() => { setDrag(null); setX(0) }}
    >
      <span className="zslide-label" style={{ opacity: Math.max(0.15, 1 - x / Math.max(1, max())) }}>{label}</span>
      <div
        className="zslide-knob"
        style={{ transform: `translateX(${x}px)`, transition: drag == null ? 'transform .2s' : 'none' }}
        onPointerDown={(e) => {
          if (disabled) return
          ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
          setDrag(e.clientX - x)
        }}
      >
        <IcArrow size={22} />
      </div>
    </div>
  )
}
