import type { OrderSnap } from '../api'
import { dict, fmtDur, type Lang } from './i18n'
import { IcBuilding, IcGate, IcHandover, IcParking } from './icons'

export function custStatus(snap: OrderSnap, lang: Lang): { text: string; tone: string } {
  const t = dict[lang]
  if (snap.customer_at_hp_at != null) return { text: t.custHere, tone: 'good' }
  if (snap.reply === 'coming') return { text: t.custComing, tone: 'good' }
  if (snap.reply === 'later2') return { text: t.custLater, tone: 'warn' }
  if (snap.reply === 'security') return { text: t.custSecurity, tone: 'info' }
  if (snap.called_at != null) return { text: t.custCalling, tone: 'warn' }
  if (snap.notified_at != null && snap.sync_enabled) return { text: t.custNotified, tone: 'accent' }
  if (snap.sync_enabled) return { text: t.custWillBeNotified(fmtDur(snap.lead_s, t)), tone: 'muted' }
  return { text: t.noSync, tone: 'muted' }
}

export function CustStrip({ snap, lang }: { snap: OrderSnap; lang: Lang }) {
  const t = dict[lang]
  const cs = custStatus(snap, lang)
  return (
    <div className={`zcust ${cs.tone}`} role="status" aria-live="polite">
      <span className="zdot" />
      <div>
        <div className="zlbl">{t.custStatus}</div>
        <div className="zval">{cs.text}</div>
      </div>
    </div>
  )
}

export function evidenceText(snap: OrderSnap, lang: Lang): string[] {
  const t = dict[lang]
  const f = snap.fair
  if (!f) return []
  if (!f.evidence_codes) return f.evidence
  return f.evidence_codes.map((c) =>
    c.code === 'within_p80' ? t.evWithinP80(fmtDur(c.handover_s, t), `p80 ${fmtDur(c.p80_s, t)}`)
      : c.code === 'customer_later' ? t.evCustLater
        : t.evCustLate(fmtDur(c.late_s, t)))
}

export function gateLabel(snap: OrderSnap, lang: Lang) {
  const t = dict[lang]
  const g = snap.gate
  return g.gate_name || (g.road ? (g.osm_gate ? t.gateOn(g.road) : t.entryOn(g.road)) : (g.osm_gate ? t.mappedGate : t.entryPoint))
}

export function ruleText(snap: OrderSnap, lang: Lang) {
  const t = dict[lang]
  return snap.handover_type === 'lobby' ? t.lobby : snap.handover_type === 'gate' ? t.gate : t.doorstep
}

/** DropSync building guide card (black header, like the app's progress card). */
export default function BuildingGuide({ snap, lang }: { snap: OrderSnap; lang: Lang }) {
  const t = dict[lang]
  const p = snap.profile
  const learned = snap.gate.source === 'learned'
  return (
    <div className="zcard zguide">
      <div className="zcard-head">
        <IcBuilding size={18} />
        <span>{t.buildingCard}</span>
        <span className="zds">DropSync</span>
      </div>
      <div className="zguide-title">
        <b>{snap.site.name}</b>
        <span>{[snap.tower.levels ? t.floors(snap.tower.levels) : null, p.trips ? t.pastDeliveries(p.trips) : null].filter(Boolean).join(' · ')}</span>
      </div>
      {snap.new_partner && learned && <div className="znew">{t.newHere}</div>}
      <div className="zrow">
        <IcGate size={20} />
        <div>
          <div className="zlbl">{t.entryGate}</div>
          <div className="zval">{learned ? gateLabel(snap, lang) : t.noHint}</div>
          {learned && <div className="zsub">{t.agreeTrips(Math.round((p.gate_agreement ?? 0) * 100), p.gate_conf ?? '')}{p.night_gate ? ` · ${t.nightGate}` : ''}</div>}
        </div>
      </div>
      <div className="zrow">
        <IcParking size={20} />
        <div>
          <div className="zlbl">{t.parkAt}</div>
          <div className="zval">{p.parking ? t.learnedParking : t.parkByGate}</div>
        </div>
      </div>
      <div className="zrow">
        <IcHandover size={20} />
        <div>
          <div className="zlbl">{t.handoverRule}</div>
          <div className="zval">{ruleText(snap, lang)}</div>
          <div className="zsub">{t.usualHandover(fmtDur(p.handover_median_s, t))}</div>
        </div>
      </div>
    </div>
  )
}
