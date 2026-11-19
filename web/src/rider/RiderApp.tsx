import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, subscribe, type LatLon, type OrderSnap, type SiteDetail, type SiteRow } from '../api'
import BuildingGuide, { CustStrip, evidenceText, gateLabel, ruleText } from './BuildingGuide'
import { dict, fmtDur, type Lang } from './i18n'
import {
  IcBazaar, IcBell, IcBuilding, IcCalendar, IcCheck, IcChevron, IcClock, IcClose, IcFeed, IcGigs,
  IcHelp, IcNav, IcPhone, IcPocket, IcSiren,
} from './icons'
import RiderMap from './RiderMap'
import Slide from './Slide'
import './rider.css'

const DROP = ['to_gate', 'gate_check', 'parking', 'walk', 'at_handover', 'indoors']
const AT_SITE = ['gate_check', 'parking', 'walk', 'at_handover', 'indoors']
/** Demo trip pay. We have no real pay data, so we use the PDF's cited typical
 *  per-order rider pay (₹20–30, PDF ref [12]) as a flat ₹25 and label it "demo". */
const DEMO_TRIP_PAY = 25
const NOMINAL_KMH = 18

const hav = (a: LatLon, b: LatLon) => {
  const R = 6371000, r = Math.PI / 180
  const dl = (b[0] - a[0]) * r, dn = (b[1] - a[1]) * r
  const h = Math.sin(dl / 2) ** 2 + Math.cos(a[0] * r) * Math.cos(b[0] * r) * Math.sin(dn / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(h))
}
const lineLen = (pts: LatLon[]) => pts.reduce((a, p, i) => (i ? a + hav(pts[i - 1], p) : 0), 0)
const kms = (m: number) => (m / 1000).toFixed(2)
const gmaps = (lat: number, lon: number) => `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}&travelmode=two-wheeler`
const orderNo = (id: string) => String(parseInt(id, 16) % 10_000_000_000).padStart(10, '45')
const hhmm = (sec: number) => `${String(Math.floor(sec / 3600)).padStart(2, '0')}:${String(Math.floor((sec % 3600) / 60)).padStart(2, '0')}`

function load<T>(k: string, d: T): T {
  try { const v = localStorage.getItem(k); return v ? (JSON.parse(v) as T) : d } catch { return d }
}
function save(k: string, v: unknown) { try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* private mode */ } }

export default function RiderApp() {
  const [lang, setLang] = useState<Lang>(() => load('ds.lang', 'en'))
  const [themePref, setThemePref] = useState<'system' | 'light' | 'dark'>(() => load('ds.theme', 'system'))
  const [sysDark, setSysDark] = useState(() => typeof matchMedia !== 'undefined' && matchMedia('(prefers-color-scheme: dark)').matches)
  const theme = themePref === 'system' ? (sysDark ? 'dark' : 'light') : themePref
  const t = dict[lang]
  const [online, setOnline] = useState(false)
  const [loginAt, setLoginAt] = useState<number | null>(null)
  const [now, setNow] = useState(Date.now())
  const [stats, setStats] = useState({ orders: 0, orderSec: 0 })
  const [snap, setSnap] = useState<OrderSnap | null>(null)
  const [sites, setSites] = useState<SiteRow[]>([])
  const [siteId, setSiteId] = useState('')
  const [detail, setDetail] = useState<SiteDetail | null>(null)
  const [towerId, setTowerId] = useState('')
  const [speed, setSpeed] = useState(10)
  const [sync, setSync] = useState(true)
  const [newPartner, setNewPartner] = useState(true)
  const [menu, setMenu] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [helped, setHelped] = useState<boolean | null>(null)
  const counted = useRef('')

  useEffect(() => { save('ds.lang', lang) }, [lang])
  useEffect(() => { save('ds.theme', themePref) }, [themePref])
  useEffect(() => {
    if (typeof matchMedia === 'undefined') return
    const mq = matchMedia('(prefers-color-scheme: dark)')
    const on = (e: MediaQueryListEvent) => setSysDark(e.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  useEffect(() => { const i = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(i) }, [])
  useEffect(() => { if (!toast) return; const i = setTimeout(() => setToast(null), 2200); return () => clearTimeout(i) }, [toast])

  useEffect(() => {
    api.sites().then((s) => {
      setSites(s)
      const usable = s.filter((x) => !x.cold_start).sort((a, b) =>
        Number(b.show_sync) - Number(a.show_sync) || Number(b.show_gate_hint) - Number(a.show_gate_hint) || b.trips - a.trips)
      if (usable.length) setSiteId(usable[0].site_id)
    }).catch((e) => setErr(String(e)))
  }, [])
  useEffect(() => {
    if (!siteId) return
    api.site(siteId).then((d) => { setDetail(d); setTowerId(d.site.towers[0]?.tower_id ?? '') })
  }, [siteId])

  const profiled = useMemo(() => sites.filter((s) => !s.cold_start), [sites])
  const home: LatLon = useMemo(() => {
    const s = sites.find((x) => x.site_id === siteId)
    return s ? [s.lat, s.lon] : [12.978, 77.717]
  }, [sites, siteId])

  useEffect(() => { if (snap?.order_id) return subscribe(snap.order_id, setSnap) }, [snap?.order_id])

  const requestOrder = useCallback(async () => {
    if (!siteId || detail?.site.site_id !== siteId) return
    try {
      const tw = detail.site.towers.find((x) => x.tower_id === towerId) ?? detail.site.towers[0]
      const o = await api.order({ site_id: siteId, tower_id: tw?.tower_id, pin_lat: tw?.lat, pin_lon: tw?.lon,
        new_partner: newPartner, sync, speedup: speed, start_dist_m: 1200, with_pickup: true, manual: true })
      setHelped(null)
      setSnap(o)
    } catch (e) { setErr(String(e)) }
  }, [siteId, towerId, detail, newPartner, sync, speed])

  // Settings changed while an order request is on screen: replace that request so the
  // new building / tower / mode takes effect right away (an accepted order is kept).
  const settingsKey = `${siteId}|${towerId}|${sync}|${newPartner}|${speed}|${detail?.site.site_id ?? ''}`
  const offerKey = useRef('')
  useEffect(() => {
    if (snap?.phase === 'offered') {
      if (offerKey.current && offerKey.current !== settingsKey && detail?.site.site_id === siteId) {
        api.action(snap.order_id, 'reject').catch(() => {})
        setSnap(null)
      }
    }
    offerKey.current = settingsKey
  }, [settingsKey, snap?.phase, snap?.order_id, detail, siteId])

  // online and idle: an order request arrives after a few seconds
  useEffect(() => {
    if (!online || snap) return
    const id = window.setTimeout(requestOrder, 3500)
    return () => window.clearTimeout(id)
  }, [online, snap, requestOrder])

  useEffect(() => {
    if (snap?.phase === 'delivered' && counted.current !== snap.order_id) {
      counted.current = snap.order_id
      setStats((s) => ({ orders: s.orders + 1, orderSec: s.orderSec + Math.max(0, (snap.delivered_at ?? 0) - (snap.accepted_at ?? 0)) }))
    }
  }, [snap])

  const act = async (a: string) => {
    if (!snap) return
    try {
      const r = await api.action(snap.order_id, a)
      setSnap(a === 'reject' ? null : r)
    } catch (e) { setErr(String(e)) }
  }

  const loginSec = loginAt ? Math.floor((now - loginAt) / 1000) : 0
  const phase = snap?.phase
  const inDrop = phase ? DROP.includes(phase) : false
  const activeOrder = snap && phase !== 'rejected'
  const pickLen = snap ? lineLen(snap.route_pickup) : 0
  const pickMins = Math.max(1, Math.round(pickLen / (NOMINAL_KMH / 3.6) / 60))

  const toggle = () => {
    if (activeOrder && phase !== 'delivered') return
    const v = !online
    setOnline(v)
    if (v && !loginAt) setLoginAt(Date.now())
    if (!v) setSnap(null)
  }

  const demoMenu = menu && (
    <div className="zmenu" role="dialog" aria-label={t.demoSettings} onClick={() => setMenu(false)}>
      <div className="zmenu-card" onClick={(e) => e.stopPropagation()}>
        <b className="zmenu-title">{t.demoSettings}</b>
        <div className="zmenu-lbl">{t.language}</div>
        <div className="zlang">
          <button className={lang === 'en' ? 'on' : ''} onClick={() => setLang('en')}>English</button>
          <button className={lang === 'hi' ? 'on' : ''} onClick={() => setLang('hi')}>हिंदी</button>
        </div>
        <div className="zmenu-lbl">{t.theme}</div>
        <div className="zlang three">
          {(['system', 'light', 'dark'] as const).map((k) => (
            <button key={k} className={themePref === k ? 'on' : ''} onClick={() => setThemePref(k)}>
              {k === 'system' ? t.themeSystem : k === 'light' ? t.themeLight : t.themeDark}
            </button>
          ))}
        </div>
        {activeOrder && phase !== 'offered' && phase !== 'delivered' && <div className="zmenu-note">{t.appliesNext}</div>}
        <label>{t.building}
          <select value={siteId} onChange={(e) => setSiteId(e.target.value)}>
            {profiled.slice().sort((a, b) => Number(b.show_sync) - Number(a.show_sync) || b.trips - a.trips).map((s) =>
              <option key={s.site_id} value={s.site_id}>{s.name} · {s.handover_type ?? '?'} · {s.confidence}{s.show_sync ? ' · sync' : ''}</option>)}
          </select>
        </label>
        <label>{t.tower}
          <select value={towerId} onChange={(e) => setTowerId(e.target.value)}>
            {detail?.site.towers.map((tw, i) => <option key={tw.tower_id} value={tw.tower_id}>{t.tower} {i + 1}{tw.levels ? ` · ${t.floors(tw.levels)}` : ''}</option>)}
          </select>
        </label>
        <label>{t.speed}
          <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
            {[5, 10, 20, 40].map((v) => <option key={v} value={v}>{v}×</option>)}
          </select>
        </label>
        <label className="zcheck"><input type="checkbox" checked={sync} onChange={(e) => setSync(e.target.checked)} /> {t.syncOn}</label>
        <label className="zcheck"><input type="checkbox" checked={newPartner} onChange={(e) => setNewPartner(e.target.checked)} /> {t.newPartner}</label>
        <div className="zhint">{t.customerPhone} <span className="mono">{location.origin}/track</span></div>
        <button className="zblack" onClick={() => setMenu(false)}>{t.close}</button>
      </div>
    </div>
  )

  /* ---------------------------------------------------------------- feed (home) */
  if (!activeOrder) {
    const tabs = [[t.feed, IcFeed], [t.pocket, IcPocket], [t.gigs, IcGigs], [t.bazaar, IcBazaar], [t.updates, IcBell]] as const
    return (
      <div className="zapp" lang={lang} data-theme={theme}>
        <div className="ztop">
          <button className={`ztoggle ${online ? 'on' : ''}`} onClick={toggle} aria-pressed={online}>
            <span className="zknob" />{online ? t.online : t.offline}
          </button>
          <div className="ztop-r">
            <button className="zround sos" aria-label="SOS" onClick={() => setToast(t.protoOnly)}><IcSiren size={20} /></button>
            <button className="zround" aria-label="Help" onClick={() => setToast(t.protoOnly)}><IcHelp size={20} /></button>
            <button className="zavatar" aria-label={t.demoSettings} onClick={() => setMenu(true)}>{lang === 'hi' ? 'रा' : 'R'}</button>
          </div>
        </div>

        <div className="zfeed">
          {err && <div className="zerr" onClick={() => setErr(null)}>{err}</div>}
          <div className={`zstatus ${online ? 'on' : ''}`}>
            {online ? <><span className="zpulse" />{t.lookingForOrders}</> : t.goOnlineHint}
          </div>

          {detail && detail.site.site_id === siteId && (
            <div className="znext">
              <span>{t.nextDrop}:</span>
              <b>{detail.site.name}{detail.site.towers.length > 1 ? ` · ${t.tower} ${Math.max(1, detail.site.towers.findIndex((x) => x.tower_id === towerId) + 1)}` : ''}</b>
            </div>
          )}

          <button className="zoutline" onClick={() => setMenu(true)}>{t.viewDetails}</button>

          <div className="zcard">
            <div className="zcard-head"><IcCalendar size={18} /><span>{t.todaysProgress}</span></div>
            <div className="zgrid">
              <div><b>₹{stats.orders * DEMO_TRIP_PAY}</b><span>{t.earnings} <i>({t.demo})</i> →</span></div>
              <div><b>{stats.orders}</b><span>{t.trips} →</span></div>
              <div><b>{hhmm(stats.orderSec)} hrs</b><span>{t.timeOnOrders} →</span></div>
              <div><b>{hhmm(loginSec)} hrs</b><span>{t.loginTime} →</span></div>
            </div>
          </div>

          <div className="zdscard">
            <div className="zdscard-ico"><IcBuilding size={26} /></div>
            <div style={{ flex: 1 }}>
              <div className="zdscard-title">{t.dsCardTitle}</div>
              <div className="zdscard-body">{t.dsCardBody(profiled.length)}</div>
            </div>
            <IcChevron size={20} />
          </div>
        </div>

        <nav className="znav" aria-label="Main">
          {tabs.map(([label, I], i) => (
            <button key={label} className={i === 0 ? 'active' : ''} aria-current={i === 0 ? 'page' : undefined}
              onClick={() => { if (i) setToast(t.protoOnly) }}>
              <I size={22} /><span>{label}</span>
            </button>
          ))}
        </nav>

        {toast && <div className="ztoast">{toast}</div>}
        {demoMenu}
      </div>
    )
  }

  /* ---------------------------------------------------------------- order screens */
  return (
    <div className="zapp order" lang={lang} data-theme={theme}>
      <RiderMap snap={snap} home={home} bottomFrac={0.58} dark={theme === 'dark'} />
      <div className="zmapbar">
        <button className="zround light" aria-label={t.demoSettings} onClick={() => setMenu(true)}>{lang === 'hi' ? 'रा' : 'R'}</button>
        {phase === 'offered'
          ? <button className="zdeny" onClick={() => act('reject')}><IcClose size={16} />{t.deny}</button>
          : inDrop && <div className="zeta">{fmtDur(snap.eta_s, t)}</div>}
      </div>

      <div className="zsheet">
        {err && <div className="zerr" onClick={() => setErr(null)}>{err}</div>}

        {phase === 'offered' && (
          <>
            <div className="zpill">{t.newOrder}</div>
            <div className="zearn">
              <span>{t.estimatedEarnings}</span>
              <b>₹{DEMO_TRIP_PAY.toFixed(2)}</b>
            </div>
            <div className="zbreak">
              <div><b>₹{DEMO_TRIP_PAY.toFixed(2)}</b><span>{t.tripPay} ({t.demo})</span></div>
              <div className="ds"><b>{fmtDur(snap.profile.handover_median_s, t)}</b><span>{t.buildingHandover}</span></div>
            </div>
            <div className="zdist">{t.pickupDrop(kms(pickLen), kms(snap.drop_distance_m))}</div>
            <hr className="zhr" />
            <div className="zplace">
              <span className="zchip">{t.pickUp}</span>
              <b>{snap.pickup?.name}</b>
              <span>{[snap.pickup?.road, 'Whitefield, Bengaluru'].filter(Boolean).join(', ')}</span>
              <span className="zmins"><IcClock size={14} /> {t.minsAway(pickMins)}</span>
            </div>
            <div className="zplace">
              <span className="zchip dark">{t.drop}</span>
              <b>{snap.site.name}</b>
              <span className="zdsline"><span className="zds">DropSync</span>{ruleText(snap, lang).split('—')[0].trim()}{snap.gate.source === 'learned' ? ` · ${gateLabel(snap, lang)}` : ''}</span>
            </div>
            <Slide label={t.acceptOrder} onDone={() => act('accept')} />
          </>
        )}

        {(phase === 'to_pickup' || phase === 'at_pickup') && snap.pickup && (
          <>
            <div className="zhead"><b>{t.headToPickup}</b><span>{Math.round(hav(snap.rider, [snap.pickup.lat, snap.pickup.lon]))} m</span></div>
            <div className="zplace">
              <span className="zchip">{t.pickUp}</span>
              <b>{snap.pickup.name}</b>
              <span>{[snap.pickup.road, snap.pickup.cuisine?.split(';').join(', ')].filter(Boolean).join(' · ')}</span>
            </div>
            <div className="zbtns">
              <a className="zbtn" href={gmaps(snap.pickup.lat, snap.pickup.lon)} target="_blank" rel="noreferrer"><IcNav size={16} />{t.navigate}</a>
              <button className="zbtn" onClick={() => setToast(t.protoOnly)}><IcPhone size={16} />{t.call}</button>
            </div>
            <Slide label={t.reachedPickup} onDone={() => act('reached_pickup')} disabled={phase !== 'at_pickup'} />
          </>
        )}

        {phase === 'pickup_wait' && (
          <>
            <Timeline snap={snap} lang={lang} />
            <div className="zhint">{t.collectCheck}</div>
            <Slide label={t.pickedUp} onDone={() => act('picked_up')} />
          </>
        )}

        {inDrop && (
          <>
            <div className="zhead"><b>{t.headToDrop}</b><span>{snap.site.name}</span></div>
            <CustStrip snap={snap} lang={lang} />
            <BuildingGuide snap={snap} lang={lang} />
            <div className="zbtns">
              <a className="zbtn" href={gmaps(snap.gate.lat, snap.gate.lon)} target="_blank" rel="noreferrer"><IcNav size={16} />{t.navigate}</a>
              <button className="zbtn" onClick={() => act('call')}><IcPhone size={16} />{t.call}</button>
            </div>
            {snap.arrived_at == null
              ? <Slide label={t.reachedDrop} onDone={() => act('reached_drop')} disabled={!AT_SITE.includes(phase!)} />
              : <Slide label={t.slideDelivered} onDone={() => act('delivered')} disabled={!(phase === 'at_handover' || phase === 'indoors')} />}
          </>
        )}

        {phase === 'delivered' && (
          <div className="zdone">
            <div className="zdone-check"><IcCheck size={30} /></div>
            <b className="zdone-title">{t.tripDone}</b>
            <div className="zdone-earn">₹{DEMO_TRIP_PAY.toFixed(2)} <i>({t.demo})</i></div>
            <div className="zkv">
              <span>{t.handoverTook}</span><b>{fmtDur(snap.fair?.handover_s, t)}</b>
              <span>{t.youWaited}</span><b>{fmtDur(snap.fair?.rider_wait_s, t)}</b>
            </div>
            {snap.fair && (
              <div className={`zfair ${snap.fair.excuse_lateness ? 'good' : ''}`}>
                <div className="zlbl">{t.lateCheck}</div>
                <div className="zval">{snap.fair.excuse_lateness ? t.notLate : t.standard}</div>
                {evidenceText(snap, lang).map((e) => <div key={e} className="zsub">• {e}</div>)}
              </div>
            )}
            {snap.gate.source === 'learned' && (
              <div className="zhelp">
                <span>{t.didHelp}</span>
                {helped == null ? (
                  <span className="zhelp-btns">
                    <button className="zbtn" onClick={() => { setHelped(true); api.helped(snap.order_id, true) }}>{t.yes}</button>
                    <button className="zbtn" onClick={() => { setHelped(false); api.helped(snap.order_id, false) }}>{t.no}</button>
                  </span>
                ) : <span className="zsub">{t.thanks}</span>}
              </div>
            )}
            <button className="zblack" onClick={() => setSnap(null)}>{t.backToFeed}</button>
          </div>
        )}
      </div>
      {toast && <div className="ztoast">{toast}</div>}
      {demoMenu}
    </div>
  )
}

/** Pickup → drop timeline, like the partner app's order list. */
function Timeline({ snap, lang }: { snap: OrderSnap; lang: Lang }) {
  const t = dict[lang]
  const no = orderNo(snap.order_id)
  const picked = snap.picked_up_at != null
  return (
    <div className="ztl">
      <div className="ztl-item">
        <span className={`ztl-dot ${picked ? 'done' : 'now'}`}>{picked && <IcCheck size={12} />}</span>
        <div>
          <b>{t.pickUp} 1</b>
          <span>{t.order}: {no}</span>
          <span>{t.pickUp}: {snap.pickup?.name}</span>
        </div>
      </div>
      <div className="ztl-item">
        <span className={`ztl-dot ${picked ? 'now' : ''}`} />
        <div>
          <b>{t.drop} 1</b>
          <span>{t.order}: {no}</span>
          <span>{t.customer}: {snap.site.name}{snap.tower.levels ? ` · ${t.floors(snap.tower.levels)}` : ''}</span>
        </div>
      </div>
    </div>
  )
}
