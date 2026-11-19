import { useState } from 'react'
import { api, fmtMin, typeLabel, type OrderSnap } from '../api'

const replyText: Record<string, { text: string; cls: string }> = {
  coming: { text: 'Customer is coming down', cls: 'pill good' },
  security: { text: 'Leave with security', cls: 'pill info' },
  later2: { text: 'Customer needs 2 more minutes', cls: 'pill warn' },
}

export default function RiderCard({ snap }: { snap: OrderSnap }) {
  const [helped, setHelped] = useState<boolean | null>(null)
  const p = snap.profile
  const learned = snap.gate.source === 'learned'
  const gateName = snap.gate.gate_name || (snap.gate.osm_gate ? 'Mapped gate' : 'Entry point')
  const custStatus = (() => {
    if (snap.delivered_at != null) return { text: 'Delivered', cls: 'pill good' }
    if (snap.customer_at_hp_at != null) return { text: 'Customer is at the handover point', cls: 'pill good' }
    if (snap.reply) return replyText[snap.reply]
    if (snap.called_at != null) return { text: 'Rider called the customer', cls: 'pill warn' }
    if (snap.notified_at != null && snap.sync_enabled) return { text: 'Customer notified to come down', cls: 'pill accent' }
    if (snap.sync_enabled) return { text: `Customer will be told to come down ${fmtMin(snap.lead_s)} before you arrive`, cls: 'pill' }
    return { text: 'No building sync for this order', cls: 'pill' }
  })()
  return (
    <div className="bcard">
      {snap.new_partner && learned && (
        <div className="newbie">New here? Follow this card: riders who used this gate were faster.</div>
      )}
      <div className="bcard-top">
        <h4>{snap.site.name}</h4>
        <div className="sub">
          {snap.tower.name || 'Tower'} · {snap.tower.levels ? `${snap.tower.levels} floors` : 'floors unknown'} ·
          ETA {snap.eta_s == null ? '—' : fmtMin(snap.eta_s)}
        </div>
      </div>
      <div className="bcard-row">
        <div className="ico">⛩</div>
        <div>
          <div className="lbl">Rider entry gate</div>
          <div className="val">{learned ? gateName : 'No confident hint'}</div>
          <div className="small muted">
            {learned
              ? `${Math.round((p.gate_agreement ?? 0) * 100)}% of fast past trips used it · ${p.gate_conf} confidence${p.night_gate ? ' · different gate at night' : ''}`
              : 'Not enough agreeing trips yet — following navigation'}
          </div>
        </div>
      </div>
      <div className="bcard-row">
        <div className="ico">P</div>
        <div>
          <div className="lbl">Park at</div>
          <div className="val">{p.parking ? 'Learned parking point (map)' : 'Beside the gate'}</div>
        </div>
      </div>
      <div className="bcard-row">
        <div className="ico">⇵</div>
        <div>
          <div className="lbl">Handover rule</div>
          <div className="val">{typeLabel[snap.handover_type] ?? snap.handover_type}</div>
          <div className="small muted">
            {p.handover?.confidence ? `${p.handover.confidence} confidence` : 'unknown'} · usual handover {fmtMin(p.handover_median_s)}
          </div>
        </div>
      </div>
      <div className="cust-status" style={{ padding: 0 }}>
        <span className={custStatus.cls} style={{ whiteSpace: 'normal' }}>{custStatus.text}</span>
      </div>
      {snap.delivered_at != null && learned && (
        <div className="bcard-row">
          <div className="ico">?</div>
          <div>
            <div className="lbl">Did this card help?</div>
            {helped == null ? (
              <div className="row" style={{ marginTop: 4 }}>
                <button className="btn" onClick={() => { setHelped(true); api.helped(snap.order_id, true) }}>Yes</button>
                <button className="btn" onClick={() => { setHelped(false); api.helped(snap.order_id, false) }}>No</button>
              </div>
            ) : <div className="small muted">Thanks — {helped ? 'kept' : 'flagged for re-learning'}.</div>}
          </div>
        </div>
      )}
      {snap.fair && (
        <div className="bcard-row">
          <div className="ico">⚖</div>
          <div>
            <div className="lbl">Lateness check</div>
            <div className="val" style={{ color: snap.fair.excuse_lateness ? 'var(--good)' : 'var(--muted)' }}>
              {snap.fair.excuse_lateness ? 'Not marked late — evidence attached' : 'Standard assessment'}
            </div>
            {snap.fair.evidence.map((e) => <div key={e} className="small muted">• {e}</div>)}
          </div>
        </div>
      )}
    </div>
  )
}
