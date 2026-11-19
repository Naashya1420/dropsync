import { useEffect, useState } from 'react'
import { MapContainer, Marker, Polygon, Polyline } from 'react-leaflet'
import L from 'leaflet'
import { api, subscribe, type Checkout, type OrderSnap } from '../api'
import { OsmTiles } from '../components/OrderMap'
import './rider.css'

const DROP = ['to_gate', 'gate_check', 'parking', 'walk', 'at_handover', 'indoors']
const riderIcon = L.divIcon({ className: '', html: '<div class="rider-dot"></div>', iconSize: [26, 26], iconAnchor: [13, 13] })
const homeIcon = L.divIcon({ className: '', html: '<div class="rpin drop"><span>⌂</span></div>', iconSize: [30, 38], iconAnchor: [15, 36] })
const fmt = (s: number | null | undefined) => (s == null ? '—' : s < 60 ? `${Math.round(s)} sec` : `${Math.max(1, Math.round(s / 60))} min`)

/** Customer phone: order tracking with the DropSync come-down nudge. Follows the
 *  latest order automatically so a second phone can just open /track. */
export default function Track() {
  const [snap, setSnap] = useState<OrderSnap | null>(null)
  const [checkout, setCheckout] = useState<Checkout | null>(null)

  useEffect(() => {
    let stop: (() => void) | null = null
    let current = ''
    const poll = async () => {
      try {
        const o = await api.latest()
        if (o.order_id !== current) {
          current = o.order_id
          stop?.()
          setSnap(o)
          stop = subscribe(o.order_id, setSnap)
          api.checkout({ site_id: o.site.site_id, tower_id: o.tower.tower_id, pin_lat: o.pin[0], pin_lon: o.pin[1] }).then(setCheckout)
        }
      } catch { /* no order yet */ }
    }
    poll()
    const i = setInterval(poll, 2500)
    return () => { clearInterval(i); stop?.() }
  }, [])

  // a finished order older than 2 minutes is not 'current' any more
  const stale = snap?.phase === 'delivered' && (snap.delivered_ago_s ?? 0) > 120
  if (!snap || snap.phase === 'rejected' || stale) {
    return (
      <div className="ctrack empty">
        <div className="rsearch"><span className="pulse" />No active order. Tracking appears here when a rider is assigned…</div>
      </div>
    )
  }
  const phase = snap.phase
  const steps = [
    { k: 'placed', label: 'Order placed', done: true },
    { k: 'assigned', label: 'Delivery partner assigned', done: snap.accepted_at != null || !snap.manual },
    { k: 'picked', label: 'Order picked up', done: snap.picked_up_at != null || (!snap.manual && phase !== 'offered') },
    { k: 'near', label: 'Arriving at your building', done: phase !== 'to_gate' && DROP.includes(phase) || phase === 'delivered' },
    { k: 'done', label: 'Delivered', done: phase === 'delivered' },
  ]
  const notif = snap.events.find((e) => e.kind === 'notify')
  const showNudge = snap.sync_enabled && snap.notified_at != null && phase !== 'delivered'
  const calling = snap.called_at != null && snap.customer_at_hp_at == null && phase !== 'delivered'
  return (
    <div className="ctrack">
      <MapContainer center={snap.rider} zoom={15} className="ctrack-map" zoomControl={false}
        bounds={L.latLngBounds([...snap.site.polygon, snap.rider])} boundsOptions={{ padding: [30, 30] }}>
        <OsmTiles />
        <Polygon positions={snap.site.polygon} pathOptions={{ weight: 2, fillOpacity: 0.1 }} />
        {DROP.includes(phase) && <Polyline positions={snap.route} pathOptions={{ weight: 4, opacity: 0.6 }} />}
        <Marker position={snap.pin} icon={homeIcon} />
        <Marker position={snap.rider} icon={riderIcon} />
      </MapContainer>
      <div className="csheet">
        {showNudge && notif && (
          <div className="cpush">
            <div className="cpush-app"><span>DropSync · Delivery update</span><span>now</span></div>
            <div className="cpush-msg">{notif.text.replace('Push to customer: ', '')}</div>
            {snap.reply == null ? (
              <div className="cpush-btns">
                <button className="main" onClick={() => api.reply(snap.order_id, 'coming')}>Coming</button>
                <button onClick={() => api.reply(snap.order_id, 'security')}>Leave with security</button>
                <button onClick={() => api.reply(snap.order_id, 'later2')}>2 more minutes</button>
              </div>
            ) : (
              <div className="cpush-ok">
                You replied: <b>{snap.reply === 'coming' ? 'Coming' : snap.reply === 'security' ? 'Leave with security' : '2 more minutes'}</b> — your rider can see it.
              </div>
            )}
          </div>
        )}
        {calling && <div className="cpush call"><div className="cpush-msg">📞 Your delivery partner is calling…</div></div>}
        <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
          <div className="rsheet-title">{phase === 'delivered' ? 'Delivered' : 'Arriving in'}</div>
          {phase !== 'delivered' && <div className="ceta">{snap.eta_s != null ? fmt(snap.eta_s) : '—'}</div>}
        </div>
        {checkout?.banner && <div className="cbanner">{checkout.banner}</div>}
        <ol className="csteps">
          {steps.map((s) => <li key={s.k} className={s.done ? 'done' : ''}>{s.label}</li>)}
        </ol>
        {snap.reply && snap.reply !== 'security' && snap.customer_at_hp_at == null && phase !== 'delivered' && (
          <button className="rprimary" onClick={() => api.here(snap.order_id)}>
            I'm at the {snap.handover_type === 'gate' ? 'gate' : 'lobby'}
          </button>
        )}
        <div className="cfoot">{snap.site.name}{snap.pickup ? ` · from ${snap.pickup.name}` : ''}</div>
      </div>
    </div>
  )
}
