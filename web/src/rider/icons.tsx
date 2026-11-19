/* Simple line icons for the rider app (drawn here; no third-party icon set). */
type P = { size?: number; className?: string }
const S = ({ size = 22, className, children }: P & { children: React.ReactNode }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.9}
    strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">{children}</svg>
)

export const IcFeed = (p: P) => <S {...p}><rect x="5" y="3.5" width="14" height="17" rx="2" /><path d="M8.5 8h7M8.5 12h7M8.5 16h4" /></S>
export const IcPocket = (p: P) => <S {...p}><path d="M4 7.5h14a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7.5Z" /><path d="M4 7.5 15.5 4v3.5" /><circle cx="16" cy="13.8" r="1.1" /></S>
export const IcGigs = (p: P) => <S {...p}><circle cx="12" cy="12" r="8.5" /><path d="M14.6 10a2.8 2.8 0 1 0 0 3.6V16a2.6 2.6 0 0 1-4.6 1.4" /></S>
export const IcBazaar = (p: P) => <S {...p}><path d="M5 8h14l-1 12H6L5 8Z" /><path d="M9 10V7a3 3 0 0 1 6 0v3" /></S>
export const IcBell = (p: P) => <S {...p}><path d="M6 16.5V11a6 6 0 1 1 12 0v5.5l1.5 1.5h-15L6 16.5Z" /><path d="M10 20.5a2 2 0 0 0 4 0" /></S>
export const IcHelp = (p: P) => <S {...p}><circle cx="12" cy="12" r="8.5" /><path d="M9.6 9.6a2.5 2.5 0 1 1 3.4 2.3c-.7.3-1 .8-1 1.5v.4" /><path d="M12 16.8h.01" /></S>
export const IcSiren = (p: P) => <S {...p}><path d="M7 17v-4a5 5 0 0 1 10 0v4" /><path d="M5 17h14v2.5H5z" /><path d="M12 3.5v2M4.5 6.5l1.4 1.4M19.5 6.5l-1.4 1.4" /></S>
export const IcClose = (p: P) => <S {...p}><path d="M6 6l12 12M18 6 6 18" /></S>
export const IcArrow = (p: P) => <S {...p}><path d="M5 12h13M13 6l6 6-6 6" /></S>
export const IcClock = (p: P) => <S {...p}><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></S>
export const IcPhone = (p: P) => <S {...p}><path d="M6.5 4h3l1.5 4-2 1.3a10 10 0 0 0 5.7 5.7l1.3-2 4 1.5v3a2 2 0 0 1-2.2 2A16 16 0 0 1 4.5 6.2 2 2 0 0 1 6.5 4Z" /></S>
export const IcNav = (p: P) => <S {...p}><path d="M12 3 20 20l-8-4-8 4 8-17Z" /></S>
export const IcCheck = (p: P) => <S {...p}><path d="m5 12.5 4.5 4.5L19 7.5" /></S>
export const IcCalendar = (p: P) => <S {...p}><rect x="4" y="5.5" width="16" height="14" rx="2" /><path d="M8 3.5v4M16 3.5v4M4 10h16M9 14l2 2 4-4" /></S>
export const IcBuilding = (p: P) => <S {...p}><path d="M5 20.5V5.5l8-2v17M13 8.5h6v12" /><path d="M8 8h2M8 11.5h2M8 15h2M16 12h.01M16 15.5h.01" /><path d="M3.5 20.5h17" /></S>
export const IcGate = (p: P) => <S {...p}><path d="M4 20V8M20 20V8M3 8h18M4 12h16" /><path d="M8 12v8M12 12v8M16 12v8" /></S>
export const IcParking = (p: P) => <S {...p}><rect x="4" y="4" width="16" height="16" rx="3" /><path d="M10 16V8h3a2.5 2.5 0 0 1 0 5h-3" /></S>
export const IcHandover = (p: P) => <S {...p}><path d="M4 14h3.5l3 2.5h5a1.5 1.5 0 0 0 0-3H12" /><path d="M7.5 14 11 11h3l5 3.5" /><rect x="10" y="3.5" width="6" height="5" rx="1" /></S>
export const IcChevron = (p: P) => <S {...p}><path d="m9 6 6 6-6 6" /></S>
export const IcBack = (p: P) => <S {...p}><path d="M19 12H6M11 6l-6 6 6 6" /></S>

/* map glyphs (white on black circles, like the reference) */
export const scooterSvg = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="17" r="2.5"/><circle cx="18" cy="17" r="2.5"/><path d="M8.5 17h7M6 14.5h4l3-5h3l2.5 7.5M13 9.5 12 6H9"/></svg>'
export const forkSvg = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 3v8M5 3v5a2 2 0 0 0 4 0V3M7 11v10M17 3c-2 1.5-3 4-3 7h3v11"/></svg>'
export const homeSvg = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 11 12 4l8 7v9H4v-9Z"/><path d="M10 20v-5h4v5"/></svg>'
