/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useMemo, useState } from 'react'
import L from 'leaflet'
import { CircleMarker, MapContainer, Polygon, Polyline, Tooltip, useMap } from 'react-leaflet'
import type { LatLon } from '../api'
import { OsmTiles } from '../components/OrderMap'

type Gate = { ap_id: string; lat: number; lon: number; osm_gate: boolean; road: string | null; label: string | null }
type Step = {
  k: number
  rider: { hint_shown: boolean; gate: string | null; probability: number | null; confidence: string | null
    handover_type: string | null; handover_conf: string | null; sync_shown: boolean; lead_s: number | null; usual_handover_s: number | null }
  gates: { ap_id: string; trips: number; refusals: number; closed: boolean; probability: number }[]
  trip?: { path: LatLon[]; read_entry: string | null; read_refused: string[]; true_entry: string; chooser: string
    wrong_gate: boolean; admitted: boolean; true_gate: string; minutes: number }
}
type Site = { site_id: string; name: string; polygon: LatLon[]; gates: Gate[]; scenarios: Record<string, Step[]> }

const SCEN: Record<string, { title: string; text: string }> = {
  first_visits: { title: 'First visits', text: 'A building with no delivery history. Deliveries arrive one by one.' },
  gate_closes: { title: 'Gate closes', text: 'Gate A works for 15 deliveries, then the guards close it and send riders to gate B.' },
  ignores_refused: { title: '11th rider ignores hint · turned away', text: 'After 10 deliveries the 11th rider ignores the hint, goes to gate B, is turned away there and comes back to A.' },
  ignores_open: { title: '11th rider ignores hint · B also works', text: 'Same, but gate B lets him in: both gates work.' },
}
const pct = (x: number | null | undefined) => (x == null ? '—' : `${Math.round(x * 100)}%`)
const mins = (s: number | null | undefined) => (s == null ? '—' : `${(s / 60).toFixed(1)} min`)
const cssVar = (n: string) => getComputedStyle(document.documentElement).getPropertyValue(n).trim()

function Fit({ poly }: { poly: LatLon[] }) {
  const map = useMap()
  const key = poly.map((p) => p.join(',')).join('|')
  useEffect(() => { map.fitBounds(L.latLngBounds(poly), { padding: [40, 40] }) }, [key]) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}

export default function Lab() {
  const [data, setData] = useState<{ sites: Site[]; note: string } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [si, setSi] = useState(0)
  const [scen, setScen] = useState('first_visits')
  const [k, setK] = useState(0)
  useEffect(() => { fetch('/api/lab').then((r) => (r.ok ? r.json() : Promise.reject(r.statusText))).then(setData).catch((e) => setErr(String(e))) }, [])
  useEffect(() => { setK(0) }, [si, scen])

  const site = data?.sites[si]
  const steps = site?.scenarios[scen] ?? []
  const step = steps[Math.min(k, steps.length - 1)]
  const gateOf = useMemo(() => Object.fromEntries((site?.gates ?? []).map((g) => [g.ap_id, g])), [site])
  const name = (id: string | null | undefined) => {
    if (!id) return '—'
    const g = gateOf[id]
    if (!g) return 'an unmapped entrance'
    const tag = g.label ? `Gate ${g.label}` : 'Gate'
    return g.road ? `${tag} (on ${g.road})` : tag
  }
  const s1 = cssVar('--series-1') || '#2a78d6'
  const s2 = cssVar('--series-2') || '#eb6834'
  const colorOf = (g: Gate) => (g.label === 'A' ? s1 : g.label === 'B' ? s2 : '#8a8a8a')

  if (err) return <div className="page"><div className="banner">Learning-stages data not available: {err}</div></div>
  if (!data || !site || !step) return <div className="page small muted">Loading…</div>

  const r = step.rider
  const t = step.trip
  const gs = new Map(step.gates.map((g) => [g.ap_id, g]))
  const why: string[] = []
  if (step.k === 0) why.push('No deliveries yet. DropSync shows nothing; the rider follows navigation, which takes him to the entrance nearest the customer\'s pin.')
  else {
    const top = step.gates.slice().sort((a, b) => b.probability - a.probability)[0]
    step.gates.filter((g) => g.closed).forEach((g) => why.push(`${name(g.ap_id)}: ${g.refusals} rider(s) turned away and nobody got in since → treated as closed; it can't be recommended.`))
    if (top) why.push(`${name(top.ap_id)}: ${top.trips} rider(s) got in here. Probability that it is the rider gate: ${pct(top.probability)}.`)
    if (r.hint_shown) why.push(`${pct(r.probability)} ≥ 90% and ${top?.trips ?? 0} ≥ 3 entries → the hint is shown (${r.confidence} confidence).`)
    else why.push(`Not shown yet: needs ≥ 90% probability from ≥ 3 entries (now ${pct(r.probability)}). Showing nothing beats showing a guess.`)
    if (r.handover_type) why.push(`Handover rule so far: ${r.handover_type} (${r.handover_conf} confidence).${r.sync_shown ? ` Come-down nudge on: customer told ${mins(r.lead_s)} before arrival.` : ' Come-down nudge needs ≥ 5 timed handovers first.'}`)
  }

  return (
    <div className="page">
      <div className="row wrap" style={{ justifyContent: 'space-between', marginBottom: 12, gap: 12 }}>
        <div>
          <h2>How DropSync learns a building</h2>
          <div className="small muted">{data.note}</div>
        </div>
        <select value={si} onChange={(e) => setSi(Number(e.target.value))} aria-label="Building">
          {data.sites.map((s, i) => <option key={s.site_id} value={i}>{s.name}</option>)}
        </select>
      </div>

      <div className="lab-tabs" role="tablist">
        {Object.entries(SCEN).map(([key, v]) => (
          <button key={key} role="tab" aria-selected={scen === key} className={scen === key ? 'on' : ''} onClick={() => setScen(key)}>{v.title}</button>
        ))}
      </div>
      <p className="small muted" style={{ margin: '6px 0 12px' }}>{SCEN[scen].text}</p>

      <div className="card card-pad lab-step">
        <div className="row wrap" style={{ gap: 10, alignItems: 'center' }}>
          <button className="btn" onClick={() => setK(Math.max(0, k - 1))} aria-label="Previous delivery">◀</button>
          <div style={{ minWidth: 220 }}>
            <div className="bold">After {step.k} past deliver{step.k === 1 ? 'y' : 'ies'}</div>
            <div className="small muted">what rider #{step.k + 1} sees</div>
          </div>
          <button className="btn" onClick={() => setK(Math.min(steps.length - 1, k + 1))} aria-label="Next delivery">▶</button>
          <input type="range" min={0} max={steps.length - 1} value={k} onChange={(e) => setK(Number(e.target.value))} style={{ flex: 1, minWidth: 160 }} aria-label="Past deliveries" />
          <div className="row wrap" style={{ gap: 6 }}>
            {[0, 1, 3, 5, 10, 11, 15, 16, 20, 25].filter((x) => x < steps.length).map((x) => (
              <button key={x} className={`btn ${k === x ? 'primary' : ''}`} onClick={() => setK(x)}>{x}</button>
            ))}
          </div>
        </div>
      </div>

      <div className="lab-grid">
        <div className="card card-pad col">
          <div className="section-title">Rider #{step.k + 1} sees</div>
          {r.hint_shown ? (
            <div className="lab-hint ok">
              <div className="small">Rider entry gate</div>
              <div className="bold" style={{ fontSize: 18 }}>{name(r.gate)}</div>
              <div className="small">{pct(r.probability)} sure · {r.confidence} confidence</div>
            </div>
          ) : (
            <div className="lab-hint">
              <div className="bold">No confident hint yet</div>
              <div className="small">Rider follows navigation (nearest entrance to the pin).</div>
            </div>
          )}
          <dl className="kv small">
            <dt>Handover rule</dt><dd>{r.handover_type ? `${r.handover_type} (${r.handover_conf})` : 'unknown'}</dd>
            <dt>Come-down nudge</dt><dd>{r.sync_shown ? `on · ${mins(r.lead_s)} before arrival` : 'off (learning)'}</dd>
            <dt>Usual handover</dt><dd>{mins(r.usual_handover_s)}</dd>
          </dl>
          {t && (
            <>
              <hr className="sep" />
              <div className="section-title">Delivery #{step.k} (behind the scenes)</div>
              <div className="small">
                {t.chooser === 'navigation' ? 'First time here: followed navigation' : t.chooser === 'forced' ? 'Ignored the hint' : t.chooser === 'stale_memory' ? 'Went to the gate he remembered' : 'Knew the building'}
                {' → '}{t.wrong_gate ? (t.admitted ? 'went to the wrong gate, guard let him in after an argument' : 'went to a gate that turned him away') : 'went straight to the right gate'}
                {` · ${t.minutes} min from reaching the site to delivered.`}
              </div>
              <div className="small" style={{ marginTop: 4 }}>
                DropSync read: got in through <b>{name(t.read_entry)}</b>{t.read_refused.length ? <>, turned away at <b>{t.read_refused.map(name).join(', ')}</b></> : ''}.
                <span className="muted"> (Truth: got in through {name(t.true_entry)}.)</span>
              </div>
            </>
          )}
        </div>

        <div className="card" style={{ overflow: 'hidden' }}>
          <MapContainer center={site.polygon[0]} zoom={17} className="lab-map" scrollWheelZoom={false}>
            <OsmTiles />
            <Fit poly={site.polygon} />
            <Polygon positions={site.polygon} pathOptions={{ color: '#2563eb', weight: 2, fillOpacity: 0.06 }} />
            {t && <Polyline positions={t.path} pathOptions={{ color: '#111', weight: 3, opacity: 0.75, dashArray: '4 6' }} />}
            {site.gates.map((g) => {
              const st = gs.get(g.ap_id)
              const p = st?.probability ?? 0
              const rec = r.hint_shown && r.gate === g.ap_id
              return (
                <CircleMarker key={g.ap_id} center={[g.lat, g.lon]} radius={8 + 16 * p}
                  pathOptions={{ color: st?.closed ? '#c62839' : rec ? '#1f7a4d' : '#fff', weight: st?.closed || rec ? 4 : 2, fillColor: colorOf(g), fillOpacity: 0.85, dashArray: st?.closed ? '3 4' : undefined }}>
                  <Tooltip permanent direction="top" className="map-label">
                    {g.label ? `Gate ${g.label}` : 'Gate'} · {pct(p)}{st?.closed ? ' · CLOSED' : ''}{rec ? ' · shown' : ''}
                  </Tooltip>
                </CircleMarker>
              )
            })}
          </MapContainer>
        </div>

        <div className="card card-pad col">
          <div className="section-title">Why</div>
          <table className="t">
            <thead><tr><th>Gate</th><th className="num">got in</th><th className="num">turned away</th><th>probability</th></tr></thead>
            <tbody>
              {site.gates.filter((g) => g.label || gs.has(g.ap_id)).map((g) => {
                const st = gs.get(g.ap_id)
                return (
                  <tr key={g.ap_id}>
                    <td><span className="dot" style={{ background: colorOf(g) }} /> {g.label ? `Gate ${g.label}` : 'Other'}{g.road ? <span className="muted"> · {g.road}</span> : null}</td>
                    <td className="num">{st?.trips ?? 0}</td>
                    <td className="num">{st?.refusals ?? 0}{st?.closed ? ' ✕' : ''}</td>
                    <td><div className="lab-bar"><span style={{ width: pct(st?.probability ?? 0), background: colorOf(g) }} /></div><span className="small">{pct(st?.probability ?? 0)}</span></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <ul className="lab-why">{why.map((w) => <li key={w}>{w}</li>)}</ul>
        </div>
      </div>
    </div>
  )
}
