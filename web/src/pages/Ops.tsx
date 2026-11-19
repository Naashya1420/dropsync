/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useMemo, useState } from 'react'
import { CircleMarker, MapContainer, Polygon, Tooltip as LTooltip } from 'react-leaflet'
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, fmtMin, typeLabel, type SiteDetail, type SiteRow } from '../api'
import { OsmTiles } from '../components/OrderMap'

const plural = (n: number, one: string, many = one + 's') => `${n} ${n === 1 ? one : many}`
const pct = (x: number | null | undefined) => (x == null ? '—' : `${Math.round(x * 100)}%`)
const cssVar = (n: string) => getComputedStyle(document.documentElement).getPropertyValue(n).trim()

function Kpi({ v, l, d, tag }: { v: string; l: string; d?: string; tag?: 'sim' | 'real' }) {
  return (
    <div className="card kpi">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <div className="l">{l}</div>
        {tag && <span className={`pill tiny ${tag === 'sim' ? 'tag-sim' : 'tag-real'}`}>{tag === 'sim' ? 'simulated' : 'real data'}</span>}
      </div>
      <div className="v">{v}</div>
      {d && <div className="d muted">{d}</div>}
    </div>
  )
}

function ProfilePanel({ id }: { id: string | null }) {
  const [d, setD] = useState<SiteDetail | null>(null)
  useEffect(() => { if (id) api.site(id).then(setD) }, [id])
  if (!id) return <div className="card card-pad muted small">Click a site on the map to inspect its learned profile.</div>
  if (!d) return <div className="card card-pad muted small">Loading…</div>
  const p = d.profile
  const g = p?.gate_day
  return (
    <div className="card card-pad col" style={{ gap: 8 }}>
      <div>
        <h3>{d.site.name}</h3>
        <div className="small muted">{d.site.kind} · {plural(d.site.towers.length, 'building')} · {plural(d.site.access_points.length, 'entry', 'entries')} ({plural(d.site.access_points.filter((a) => a.osm_gate).length, 'OSM gate')})</div>
      </div>
      {!p ? <div className="small muted">Cold start: no delivery history. Nothing is shown to riders or customers.</div> : (
        <>
          <div className="row wrap">
            <span className={`pill ${p.confidence === 'high' ? 'good' : p.confidence === 'medium' ? 'warn' : ''}`}>{p.confidence} confidence</span>
            <span className="pill">{p.trips} trips</span>
            {p.show_gate_hint && <span className="pill accent">gate hint on</span>}
            {p.show_sync && <span className="pill info">come-down sync on</span>}
          </div>
          <dl className="kv small">
            <dt>Rider gate</dt>
            <dd>{g ? `${g.gate_name || (g.in_osm ? 'OSM gate' : 'entry (no gate tag in OSM)')} · ${pct(g.agreement)} agree · ${g.trips} trips` : '—'}</dd>
            <dt>Faster than others</dt><dd>{g ? (g.faster_than_alternatives ? 'yes' : 'no — hint suppressed') : '—'}</dd>
            <dt>Night gate</dt><dd>{p.gate_night ? `different after 23:00 (${pct(p.gate_night.agreement)} agree)` : 'same as day'}</dd>
            <dt>Parking</dt><dd>{p.parking ? `${p.parking.inside_site ? 'inside' : 'outside'} site · ${pct(p.parking.share)} of trips${p.parking.snapped_to_osm_parking ? ' · OSM parking' : ''}` : '—'}</dd>
            <dt>Handover</dt><dd>{p.handover ? `${typeLabel[p.handover.type]} · ${pct(p.handover.agreement)} agree` : '—'}</dd>
            <dt>Votes</dt><dd>{p.handover ? Object.entries(p.handover.votes).map(([k, v]) => `${k} ${pct(v as number)}`).join(' · ') : '—'}</dd>
            <dt>Handover time</dt><dd>{p.handover_time_s ? `median ${fmtMin(p.handover_time_s.median)} · p80 ${fmtMin(p.handover_time_s.p80)}` : '—'}</dd>
            <dt>Come-down lead</dt><dd>{fmtMin(p.come_down_lead_s)}</dd>
            <dt>Floors (OSM)</dt><dd>{p.osm_levels?.towers_with_levels ? `median ${p.osm_levels.median} (${p.osm_levels.towers_with_levels}/${p.osm_levels.towers} tagged)` : 'not tagged'}</dd>
          </dl>
          {g?.alternatives?.length > 0 && (
            <div className="small muted">Other entries used: {g.alternatives.map((a: any) => `${a.trips} trips (${fmtMin(a.median_handover_s)})`).join(', ')}</div>
          )}
        </>
      )}
    </div>
  )
}

function SiteMap({ sites, onPick, picked }: { sites: SiteRow[]; onPick: (id: string) => void; picked: string | null }) {
  const colors: Record<string, string> = {
    high: cssVar('--conf-high'), medium: cssVar('--conf-medium'), low: cssVar('--conf-low'), none: cssVar('--conf-none'),
  }
  const accent = cssVar('--accent')
  if (!sites.length) return <div className="ops-map card" />
  const c: [number, number] = [sites.reduce((a, s) => a + s.lat, 0) / sites.length, sites.reduce((a, s) => a + s.lon, 0) / sites.length]
  return (
    <MapContainer center={c} zoom={15} className="ops-map" scrollWheelZoom={false}>
      <OsmTiles />
      {sites.map((s) => (
        <Polygon key={s.site_id} positions={s.polygon} eventHandlers={{ click: () => onPick(s.site_id) }}
          pathOptions={{ color: s.site_id === picked ? accent : colors[s.confidence], weight: s.site_id === picked ? 3 : 1.5, fillOpacity: s.cold_start ? 0.04 : 0.25 }}>
          <LTooltip sticky>{s.name} · {s.cold_start ? 'no history' : `${s.confidence}, ${s.trips} trips${s.handover_type ? ', ' + s.handover_type : ''}`}</LTooltip>
        </Polygon>
      ))}
      {sites.filter((s) => s.gate && s.show_gate_hint).map((s) => (
        <CircleMarker key={'g' + s.site_id} center={[s.gate!.lat, s.gate!.lon]} radius={4}
          pathOptions={{ color: accent, fillColor: accent, fillOpacity: 1, weight: 1 }} eventHandlers={{ click: () => onPick(s.site_id) }}>
          <LTooltip>Learned rider gate · {s.name}</LTooltip>
        </CircleMarker>
      ))}
    </MapContainer>
  )
}

export default function Ops() {
  const [sites, setSites] = useState<SiteRow[]>([])
  const [m, setM] = useState<any>(null)
  const [meta, setMeta] = useState<any>(null)
  const [picked, setPicked] = useState<string | null>(null)
  useEffect(() => {
    api.sites().then((s) => {
      setSites(s)
      const top = s.filter((x) => x.show_sync && x.show_gate_hint).sort((a, b) => b.trips - a.trips)[0]
      if (top) setPicked(top.site_id)
    })
    api.metrics().then(setM)
    api.meta().then(setMeta)
  }, [])
  const s1 = cssVar('--series-1')
  const s2 = cssVar('--series-2')
  const grid = cssVar('--grid')
  const muted = cssVar('--muted')
  const mm = m?.metrics
  const acc = mm?.profile_accuracy
  const ab = mm?.ab_sync?.lobby_gate_orders
  const fb = mm?.ab_sync?.after_feedback?.lobby_gate_orders
  const hist = useMemo(() => {
    const h = mm?.ab_sync?.histogram
    if (!h) return []
    return h.today.map((v: number, i: number) => ({ bin: `${h.bins_s[i] / 60}–${h.bins_s[i + 1] / 60}`, Today: v, DropSync: h.dropsync[i] }))
  }, [mm])
  const conf = useMemo(() => {
    const c: Record<string, number> = { high: 0, medium: 0, low: 0, none: 0 }
    sites.forEach((s) => { c[s.confidence] = (c[s.confidence] ?? 0) + 1 })
    return c
  }, [sites])

  return (
    <div className="page">
      <div className="row wrap" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
        <div>
          <h2>Ops dashboard</h2>
          <div className="small muted">{meta?.study?.label} · {String(meta?.study?.why ?? '').split('>=').join('≥')}</div>
        </div>
        <div className="row wrap small">
          {meta?.sources?.map((s: any) => <span key={s.name} className={`pill ${s.kind === 'real' ? 'tag-real' : 'tag-sim'}`}>{s.kind}: {s.name}</span>)}
          <span className="pill">profiles from {meta?.profile_source}</span>
        </div>
      </div>

      <div className="kpis">
        <Kpi tag="sim" l="Rider gate hint precision" v={pct(acc?.gate_hint_precision)} d={`shown at ${pct(acc?.gate_hint_coverage)} of sites · navigation alone picks right ${pct(mm?.baselines?.navigation_gate_correct)}`} />
        <Kpi tag="sim" l="Handover rule accuracy" v={pct(acc?.handover_type_accuracy_shown)} d={`where shown at checkout (${pct(acc?.checkout_banner_coverage)} of sites)`} />
        <Kpi tag="sim" l="Rider wait at handover (median)" v={ab ? fmtMin(ab.rider_wait_at_handover_s.dropsync_median) : '—'} d={ab ? `today ${fmtMin(ab.rider_wait_at_handover_s.today_median)} · lobby/gate orders` : ''} />
        <Kpi tag="sim" l="Calls needed" v={ab ? pct(ab.call_rate.dropsync) : '—'} d={ab ? `today ${pct(ab.call_rate.today)}` : ''} />
        <Kpi tag="sim" l="Rider-minutes saved / order" v={ab ? ab.rider_minutes_saved_per_order.toFixed(2) : '—'} d={mm?.sizing ? `→ ₹${mm.sizing.share_20pct.rupees_crore_per_year}–${mm.sizing.share_30pct.rupees_crore_per_year} cr/yr Blinkit (PDF formula)` : ''} />
        <Kpi tag="real" l="GPS noise (measured)" v={m?.noise ? `σ ${m.noise.stationary.sigma_per_axis_m} m` : '—'} d={m?.noise ? `${m.noise.raw_points.toLocaleString()} real OSM trace points · spikes ${(m.noise.spike_rate * 100).toFixed(2)}%` : ''} />
      </div>

      <div className="ops-grid">
        <div className="card" style={{ overflow: 'hidden' }}>
          <SiteMap sites={sites} onPick={setPicked} picked={picked} />
          <div className="legend" style={{ padding: '8px 12px' }}>
            {(['high', 'medium', 'low', 'none'] as const).map((k) => (
              <span key={k} className="row" style={{ gap: 5 }}><span className="dot" style={{ background: `var(--conf-${k})` }} />{k === 'none' ? 'no history' : k} ({conf[k] ?? 0})</span>
            ))}
            <span className="row" style={{ gap: 5 }}><span className="dot" style={{ background: 'var(--accent)' }} />learned rider gate</span>
          </div>
        </div>
        <ProfilePanel id={picked} />
      </div>

      <div className="charts">
        <div className="card card-pad chart-card">
          <h3>Handover time, lobby &amp; gate orders</h3>
          <p className="small muted">Rider reaches the site → delivered. Out-of-sample orders (days 60–89), today vs replayed with DropSync. Simulated.</p>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={hist} barGap={2} margin={{ left: 0, right: 8 }}>
              <CartesianGrid vertical={false} stroke={grid} />
              <XAxis dataKey="bin" tick={{ fill: muted, fontSize: 11 }} label={{ value: 'minutes', position: 'insideBottomRight', offset: -4, fill: muted, fontSize: 11 }} />
              <YAxis tick={{ fill: muted, fontSize: 11 }} width={40} />
              <Tooltip />
              <Legend />
              <Bar dataKey="Today" fill={s1} radius={[4, 4, 0, 0]} />
              <Bar dataKey="DropSync" fill={s2} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
          {ab && <div className="small muted">Median {fmtMin(ab.handover_time_s.today_median)} → {fmtMin(ab.handover_time_s.dropsync_median)} · customer waits median {fmtMin(ab.customer_wait_at_handover_s.dropsync_median)} (p80 {fmtMin(ab.customer_wait_at_handover_s.dropsync_p80)}) · nudges followed {pct(mm?.ab_sync?.nudge_followed_rate)}</div>}
          {fb && <div className="small muted" style={{ marginTop: 4 }}>After feedback (lead learned from "Coming" tap → arrival): handover median {fmtMin(fb.handover_time_s.dropsync_median)}, customer waits median {fmtMin(fb.customer_wait_at_handover_s.dropsync_median)} (p80 {fmtMin(fb.customer_wait_at_handover_s.dropsync_p80)}), rider waits mean {fmtMin(fb.rider_wait_at_handover_s.dropsync_mean)}.</div>}
        </div>

        <div className="card card-pad chart-card">
          <h3>How many trips a building needs</h3>
          <p className="small muted">Accuracy when a profile is learned from k random trips (multi-gate sites). Simulated.</p>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={(mm?.learning_curve ?? []).map((r: any) => ({ trips: r.trips, 'Rider gate': r.gate_accuracy_multi_gate, 'Handover rule': r.handover_type_accuracy }))} margin={{ left: 0, right: 16, top: 10 }}>
              <CartesianGrid vertical={false} stroke={grid} />
              <XAxis dataKey="trips" tick={{ fill: muted, fontSize: 11 }} label={{ value: 'trips per building', position: 'insideBottomRight', offset: -4, fill: muted, fontSize: 11 }} />
              <YAxis domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} tick={{ fill: muted, fontSize: 11 }} width={44} />
              <Tooltip formatter={(v: number) => pct(v)} />
              <Legend />
              <Line type="monotone" dataKey="Rider gate" stroke={s1} strokeWidth={2} dot={{ r: 4 }} />
              <Line type="monotone" dataKey="Handover rule" stroke={s2} strokeWidth={2} dot={{ r: 4 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="card card-pad chart-card">
          <h3>Profile accuracy vs ground truth</h3>
          <p className="small muted">Learned on days 0–59 of the simulated history; truth is hidden from the builder.</p>
          <table className="t">
            <tbody>
              <tr><td>Rider gate, all sites with a profile</td><td className="num">{pct(acc?.gate_accuracy_all)}</td></tr>
              <tr><td>Rider gate, sites with ≥2 entries</td><td className="num">{pct(acc?.gate_accuracy_multi_gate)}</td></tr>
              <tr><td>Gate hint precision (only when shown)</td><td className="num">{pct(acc?.gate_hint_precision)}</td></tr>
              <tr><td>Night gate found (sites with ≥6 night trips / all where it differs)</td><td className="num">{pct(acc?.night_gate_recall_enough_trips)} of {acc?.night_gate_sites_with_enough_trips} / {pct(acc?.night_gate_recall)} of {acc?.night_gate_sites}</td></tr>
              <tr><td>Night gate false alarms</td><td className="num">{pct(acc?.night_gate_false_alarm_rate)}</td></tr>
              <tr><td>Handover rule (all / shown)</td><td className="num">{pct(acc?.handover_type_accuracy)} / {pct(acc?.handover_type_accuracy_shown)}</td></tr>
              <tr><td>Parking point error (median / p80)</td><td className="num">{acc?.parking_error_m?.median?.toFixed(0)} m / {acc?.parking_error_m?.p80?.toFixed(0)} m</td></tr>
              <tr><td>Handover time error (median)</td><td className="num">{fmtMin(acc?.handover_time_abs_error_s?.median)}</td></tr>
              <tr><td>Gate changed on day 60: right after, with recency / without</td><td className="num">{pct(mm?.recency?.with_recency)} / {pct(mm?.recency?.without_recency)} ({mm?.recency?.sites} sites)</td></tr>
              <tr><td>Pin fixer precision / recall</td><td className="num">{pct(mm?.pin_fixer?.precision)} / {pct(mm?.pin_fixer?.recall)}</td></tr>
            </tbody>
          </table>
        </div>

        <div className="card card-pad chart-card">
          <h3>Robustness to GPS quality</h3>
          <p className="small muted">Re-simulated with noisier GPS and sparser pings (25 multi-gate sites, 60 orders each).</p>
          <table className="t">
            <thead><tr><th>GPS σ</th><th className="num">ping every</th><th className="num">gate acc.</th><th className="num">rule acc.</th></tr></thead>
            <tbody>
              {(mm?.robustness ?? []).map((r: any) => (
                <tr key={`${r.noise_scale}-${r.ping_interval_s}`}><td>{r.noise_sigma_m} m (×{r.noise_scale})</td><td className="num">{r.ping_interval_s} s</td><td className="num">{pct(r.gate_accuracy_multi_gate)}</td><td className="num">{pct(r.handover_type_accuracy)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card card-pad chart-card">
          <h3>Why Bengaluru (measured OSM coverage)</h3>
          <p className="small muted">Equal 0.30° box per metro; societies, office parks and malls only. Real OSM data.</p>
          <table className="t">
            <thead><tr><th>City</th><th className="num">sites</th><th className="num">≥1 gate</th><th className="num">≥2 gates</th><th className="num">floors tagged</th></tr></thead>
            <tbody>
              {(m?.cities?.rows ?? []).map((r: any) => (
                <tr key={r.city} style={r.city === m.cities.chosen?.city ? { fontWeight: 700 } : undefined}>
                  <td>{r.city}</td><td className="num">{r.sites.toLocaleString()}</td><td className="num">{r.sites_with_gate.toLocaleString()}</td>
                  <td className="num">{r.sites_multi_gate.toLocaleString()}</td><td className="num">{r.bldg_levels.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card card-pad chart-card">
          <h3>Campus field trial (IIIT Allahabad)</h3>
          <p className="small muted">Real phone GPS from the Field trial logger. OSM has no campus gates, so the team surveys them.</p>
          <dl className="kv small">
            <dt>Trips recorded</dt><dd>{m?.field?.trips ?? 0} (control {m?.field?.by_variant?.control ?? 0} · sync {m?.field?.by_variant?.sync ?? 0})</dd>
            <dt>Gates surveyed</dt><dd>{m?.field?.gates ?? 0}</dd>
            <dt>Gate inference</dt><dd>{m?.field?.results?.gate_inference_accuracy != null ? pct(m.field.results.gate_inference_accuracy) : 'pending trips'}</dd>
            <dt>Rider wait median</dt><dd>{m?.field?.results?.control ? `control ${fmtMin(m.field.results.control.rider_wait_s_median)} · sync ${fmtMin(m.field.results.sync.rider_wait_s_median)}` : 'pending trips'}</dd>
          </dl>
        </div>
      </div>
    </div>
  )
}
