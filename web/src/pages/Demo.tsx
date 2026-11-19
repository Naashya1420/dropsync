import { useEffect, useMemo, useState } from 'react'
import { api, fmtMin, subscribe, typeLabel, type Checkout, type OrderSnap, type SiteDetail, type SiteRow } from '../api'
import CustomerScreen from '../components/CustomerScreen'
import OrderMap from '../components/OrderMap'
import RiderCard from '../components/RiderCard'

function Phone({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="phone">
        <div className="phone-screen">
          <div className="phone-status"><span>9:41</span><span>4G ▮▮▮</span></div>
          <div className="phone-head"><h3>{title}</h3></div>
          <div className="phone-body">{children}</div>
        </div>
      </div>
    </div>
  )
}

export default function Demo() {
  const [sites, setSites] = useState<SiteRow[]>([])
  const [siteId, setSiteId] = useState<string>('')
  const [detail, setDetail] = useState<SiteDetail | null>(null)
  const [towerId, setTowerId] = useState<string>('')
  const [newPartner, setNewPartner] = useState(true)
  const [sync, setSync] = useState(true)
  const [speed, setSpeed] = useState(8)
  const [checkout, setCheckout] = useState<Checkout | null>(null)
  const [snap, setSnap] = useState<OrderSnap | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [pinOverride, setPinOverride] = useState<[number, number] | null>(null)

  useEffect(() => {
    api.sites().then((s) => {
      const usable = s.filter((x) => !x.cold_start).sort((a, b) =>
        Number(b.show_sync) - Number(a.show_sync) || Number(b.show_gate_hint) - Number(a.show_gate_hint) || b.trips - a.trips)
      setSites(usable)
      if (usable.length) setSiteId(usable[0].site_id)
    }).catch((e) => setErr(String(e)))
  }, [])

  useEffect(() => {
    if (!siteId) return
    setSnap(null)
    api.site(siteId).then((d) => {
      setDetail(d)
      setTowerId(d.site.towers[0]?.tower_id ?? '')
      setPinOverride(null)
    })
  }, [siteId])

  useEffect(() => {
    if (!siteId || !detail) return
    const t = detail.site.towers.find((x) => x.tower_id === towerId)
    const pin = pinOverride ?? (t ? [t.lat, t.lon] as [number, number] : null)
    api.checkout({ site_id: siteId, tower_id: towerId || undefined, pin_lat: pin?.[0], pin_lon: pin?.[1] }).then(setCheckout)
  }, [siteId, towerId, detail, pinOverride])

  useEffect(() => {
    if (!snap?.order_id) return
    return subscribe(snap.order_id, setSnap)
  }, [snap?.order_id])

  const site = useMemo(() => sites.find((s) => s.site_id === siteId), [sites, siteId])

  const place = async () => {
    setBusy(true)
    setErr(null)
    try {
      const t = detail?.site.towers.find((x) => x.tower_id === towerId)
      const pin = pinOverride ?? (t ? [t.lat, t.lon] : null)
      const o = await api.order({ site_id: siteId, tower_id: towerId || undefined, pin_lat: pin?.[0], pin_lon: pin?.[1],
        new_partner: newPartner, sync, speedup: speed, start_dist_m: 1200 })
      setSnap(o)
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  const waitDone = snap?.events.find((e) => e.kind === 'delivered')

  return (
    <div className="page">
      <div className="card controls">
        <label>Building (learned profiles, Bengaluru study zone)
          <select value={siteId} onChange={(e) => setSiteId(e.target.value)}>
            {sites.map((s) => (
              <option key={s.site_id} value={s.site_id}>
                {s.name} · {s.handover_type ?? '?'} · {s.confidence}{s.show_sync ? ' · sync' : ''}
              </option>
            ))}
          </select>
        </label>
        <label>Tower
          <select value={towerId} onChange={(e) => setTowerId(e.target.value)}>
            {detail?.site.towers.map((t, i) => (
              <option key={t.tower_id} value={t.tower_id}>Tower {i + 1}{t.levels ? ` · ${t.levels} floors (OSM)` : ''}</option>
            ))}
          </select>
        </label>
        <label>Replay speed
          <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
            {[4, 8, 15, 30].map((v) => <option key={v} value={v}>{v}× real time</option>)}
          </select>
        </label>
        <div className="col" style={{ gap: 6 }}>
          <label className="check"><input type="checkbox" checked={newPartner} onChange={(e) => setNewPartner(e.target.checked)} /> New partner (first visit)</label>
          <label className="check"><input type="checkbox" checked={sync} onChange={(e) => setSync(e.target.checked)} /> DropSync on (uncheck = today)</label>
        </div>
        <button className="btn primary" disabled={!siteId || busy} onClick={place}>{busy ? 'Assigning…' : 'Place order & assign rider'}</button>
      </div>
      {err && <div className="banner" style={{ marginBottom: 12, background: 'var(--accent-soft)', color: 'var(--accent)' }}>{err}</div>}

      <div className="demo-grid">
        <div>
          <Phone title="Delivery partner">
            {snap ? <RiderCard snap={snap} /> : (
              <div className="card card-pad small muted">
                Place an order to see the building card the rider gets on assignment.
                {site && <><hr className="sep" />
                  <b>{site.name}</b><br />
                  Learned from {site.trips} past trips · {site.confidence} confidence<br />
                  {site.handover_type && <>Rule: {typeLabel[site.handover_type]}<br /></>}
                  Usual handover {fmtMin(site.handover_median_s)}</>}
              </div>
            )}
          </Phone>
          <p className="phone-label">Rider app · building card</p>
        </div>

        <div className="map-col col">
          <div className="card" style={{ overflow: 'hidden' }}>
            <OrderMap snap={snap} className="demo-map" home={site?.polygon} />
          </div>
          <div className="card card-pad">
            <div className="row" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
              <div className="section-title" style={{ margin: 0 }}>Live order timeline</div>
              {snap && <span className="pill">{snap.phase.replace('_', ' ')} · t+{fmtMin(snap.sim_t)}</span>}
            </div>
            {snap ? (
              <>
                <div className="small muted" style={{ marginBottom: 8 }}>
                  Come-down lead: <b>{fmtMin(snap.lead_s)}</b> — {snap.lead_explain}.
                  {!snap.sync_enabled && ' Sync off: the rider calls on arrival, as today.'}
                </div>
                <div className="timeline">
                  {snap.events.map((e, i) => (
                    <div key={i} className={`ev ${e.kind}`}><span className="t">{fmtMin(e.t)}</span><span className="x">{e.text}</span></div>
                  ))}
                </div>
                {waitDone && (
                  <div className="row wrap" style={{ marginTop: 10 }}>
                    <span className="pill good">Rider waited at handover point: {fmtMin(waitDone.rider_wait_s ?? 0)}</span>
                    {snap.fair?.handover_s != null && <span className="pill info">Handover (boundary → delivered): {fmtMin(snap.fair.handover_s)}</span>}
                    {snap.profile.handover_median_s != null && <span className="pill">Building's usual handover today: {fmtMin(snap.profile.handover_median_s)}</span>}
                  </div>
                )}
              </>
            ) : <div className="small muted">Map shows the real OSM site boundary, mapped gates (blue) and road/path entries (grey). The red dot is the rider gate DropSync learned.</div>}
          </div>
        </div>

        <div>
          <Phone title="Customer">
            <CustomerScreen snap={snap} checkout={checkout} onFixPin={(lat, lon) => setPinOverride([lat, lon])} />
          </Phone>
          <p className="phone-label">Customer app · checkout banner, timed nudge, one-tap replies</p>
        </div>
      </div>
    </div>
  )
}
