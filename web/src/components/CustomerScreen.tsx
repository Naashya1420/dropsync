import { api, fmtMin, type Checkout, type OrderSnap } from '../api'

export default function CustomerScreen({ snap, checkout, onFixPin }: { snap: OrderSnap | null; checkout: Checkout | null; onFixPin?: (lat: number, lon: number) => void }) {
  const notifEvent = snap?.events.find((e) => e.kind === 'notify')
  const showNotif = snap && snap.sync_enabled && snap.notified_at != null
  const calling = snap && snap.called_at != null && snap.delivered_at == null
  return (
    <div className="col">
      {checkout?.banner && <div className="banner">{checkout.banner}</div>}
      {checkout?.pin_fix && (
        <div className="banner" style={{ background: 'var(--warn-soft)', color: 'var(--warn)' }}>
          {checkout.pin_fix.reason}{' '}
          {onFixPin && !snap && (
            <button className="linkbtn" onClick={() => onFixPin(checkout.pin_fix!.suggest.lat, checkout.pin_fix!.suggest.lon)}>Fix my pin</button>
          )}
        </div>
      )}
      <div className="card card-pad">
        <div className="small muted">Arriving in</div>
        <div className="eta-big">
          {snap?.delivered_at != null ? 'Delivered' : snap?.eta_s != null ? fmtMin(snap.eta_s) : checkout ? `${checkout.eta_min} min` : '—'}
        </div>
        {checkout && checkout.eta_building_add_min > 0 && !snap && (
          <div className="small muted">includes {checkout.eta_building_add_min} min usual handover time for your building</div>
        )}
        {snap && <div className="small muted">{snap.site.name}</div>}
      </div>
      {showNotif && notifEvent && (
        <div className="notif">
          <div className="app"><span>DropSync · Delivery</span><span>now</span></div>
          <div className="msg">{notifEvent.text.replace('Push to customer: ', '')}</div>
          {snap.delivered_at == null && (
            <div className="replies">
              <button className={`main ${snap.reply === 'coming' ? 'picked' : ''}`} onClick={() => api.reply(snap.order_id, 'coming')}>Coming</button>
              <button className={snap.reply === 'security' ? 'picked' : ''} onClick={() => api.reply(snap.order_id, 'security')}>Leave with security</button>
              <button className={snap.reply === 'later2' ? 'picked' : ''} onClick={() => api.reply(snap.order_id, 'later2')}>2 more minutes</button>
            </div>
          )}
        </div>
      )}
      {calling && snap.customer_at_hp_at == null && (
        <div className="notif"><div className="app"><span>Phone</span><span>now</span></div>
          <div className="msg">📞 Incoming call from your delivery partner — "I'm downstairs, please come"</div></div>
      )}
      {snap && snap.reply && snap.reply !== 'security' && snap.customer_at_hp_at == null && snap.delivered_at == null && (
        <button className="btn primary block" onClick={() => api.here(snap.order_id)}>I'm at the {snap.handover_type}</button>
      )}
      {snap?.delivered_at != null && (
        <div className="card card-pad">
          <div className="bold">Order delivered</div>
          <div className="small muted">Handover {snap.fair?.handover_s != null ? fmtMin(snap.fair.handover_s) : '—'} from reaching your building.</div>
        </div>
      )}
    </div>
  )
}
