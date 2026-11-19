/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useRef, useState } from 'react'
import { api } from '../api'

type Pt = { ts: number; lat: number; lon: number; accuracy_m: number | null }

const now = () => Date.now() / 1000

export default function Trial() {
  const [summary, setSummary] = useState<any>(null)
  const [recording, setRecording] = useState(false)
  const [points, setPoints] = useState<Pt[]>([])
  const [variant, setVariant] = useState<'control' | 'sync'>('control')
  const [destination, setDestination] = useState('')
  const [actualGate, setActualGate] = useState('')
  const [htype, setHtype] = useState('lobby')
  const [called, setCalled] = useState(false)
  const [marks, setMarks] = useState<{ arrived?: number; ready?: number; delivered?: number }>({})
  const [gateName, setGateName] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  const watch = useRef<number | null>(null)
  const geoOk = typeof navigator !== 'undefined' && 'geolocation' in navigator && window.isSecureContext

  const refresh = () => api.trialSummary().then(setSummary).catch(() => {})
  useEffect(() => { refresh() }, [])

  const start = () => {
    setPoints([])
    setMarks({})
    setCalled(false)
    setMsg(null)
    watch.current = navigator.geolocation.watchPosition(
      (p) => setPoints((xs) => [...xs, { ts: p.timestamp / 1000, lat: p.coords.latitude, lon: p.coords.longitude, accuracy_m: p.coords.accuracy ?? null }]),
      (e) => setMsg(`GPS error: ${e.message}`),
      { enableHighAccuracy: true, maximumAge: 0, timeout: 20000 },
    )
    setRecording(true)
  }

  const stop = async () => {
    if (watch.current != null) navigator.geolocation.clearWatch(watch.current)
    setRecording(false)
    const body = {
      trip_id: `${Date.now()}`, variant, destination, actual_gate: actualGate || null, handover_type: htype,
      arrived_ts: marks.arrived ?? null, customer_ready_ts: marks.ready ?? null, delivered_ts: marks.delivered ?? null,
      called, points,
    }
    try {
      const r: any = await api.trialTrip(body)
      setMsg(`Uploaded ${r.points} GPS points.`)
      refresh()
    } catch (e) {
      setMsg(`Upload failed: ${e}`)
    }
  }

  const markGate = () => {
    if (!gateName) { setMsg('Name the gate first'); return }
    navigator.geolocation.getCurrentPosition(async (p) => {
      await api.trialGate({ name: gateName, lat: p.coords.latitude, lon: p.coords.longitude, accuracy_m: p.coords.accuracy, rider_allowed: true })
      setMsg(`Gate "${gateName}" saved (±${Math.round(p.coords.accuracy)} m).`)
      setGateName('')
      refresh()
    }, (e) => setMsg(`GPS error: ${e.message}`), { enableHighAccuracy: true, timeout: 20000 })
  }

  const last = points[points.length - 1]
  const gates: any[] = summary?.gate_list ?? []

  return (
    <div className="page" style={{ maxWidth: 560 }}>
      <h2>Campus field trial</h2>
      <p className="small muted">IIIT Allahabad (PDF §4.4). Rider phone records GPS; the team writes down the gate actually used. Control = rider calls on arrival as today; sync = customer is told to come down using the building card.</p>
      {!geoOk && <div className="banner" style={{ background: 'var(--warn-soft)', color: 'var(--warn)' }}>Location needs HTTPS on phones. Run <span className="mono">npm run dev:https</span> and open the https:// address.</div>}

      <div className="card card-pad col" style={{ marginTop: 12 }}>
        <div className="section-title">1 · Survey gates (once)</div>
        <div className="row">
          <input type="text" placeholder="Gate name, e.g. Main gate" value={gateName} onChange={(e) => setGateName(e.target.value)} style={{ flex: 1 }} />
          <button className="btn" disabled={!geoOk} onClick={markGate}>Mark gate here</button>
        </div>
        <div className="small muted">{gates.length ? gates.map((g) => g.name).join(' · ') : 'No gates surveyed yet.'}</div>
      </div>

      <div className="card card-pad col" style={{ marginTop: 12 }}>
        <div className="section-title">2 · Record a mock delivery</div>
        <div className="row wrap">
          <label className="check"><input type="radio" checked={variant === 'control'} onChange={() => setVariant('control')} /> Control (today)</label>
          <label className="check"><input type="radio" checked={variant === 'sync'} onChange={() => setVariant('sync')} /> DropSync sync</label>
        </div>
        <input type="text" placeholder="Destination (hostel / block)" value={destination} onChange={(e) => setDestination(e.target.value)} />
        <div className="row">
          {!recording
            ? <button className="btn primary block" disabled={!geoOk || !destination} onClick={start}>Start trip</button>
            : <button className="btn primary block" onClick={stop}>Finish &amp; upload</button>}
        </div>
        {recording && (
          <>
            <div className="small">{points.length} fixes · last ±{last?.accuracy_m ? Math.round(last.accuracy_m) : '—'} m</div>
            <div className="row wrap">
              <button className="btn" onClick={() => setMarks((m) => ({ ...m, arrived: now() }))}>{marks.arrived ? '✓ ' : ''}Arrived</button>
              <button className="btn" onClick={() => setMarks((m) => ({ ...m, ready: now() }))}>{marks.ready ? '✓ ' : ''}Customer at handover</button>
              <button className="btn" onClick={() => setMarks((m) => ({ ...m, delivered: now() }))}>{marks.delivered ? '✓ ' : ''}Delivered</button>
            </div>
            <label className="check"><input type="checkbox" checked={called} onChange={(e) => setCalled(e.target.checked)} /> Rider had to call the customer</label>
            <select value={actualGate} onChange={(e) => setActualGate(e.target.value)}>
              <option value="">Gate actually used (observer)…</option>
              {gates.map((g) => <option key={g.name + g.ts} value={g.name}>{g.name}</option>)}
            </select>
            <select value={htype} onChange={(e) => setHtype(e.target.value)}>
              <option value="lobby">Handover at lobby</option><option value="gate">Handover at gate</option><option value="doorstep">Doorstep</option>
            </select>
          </>
        )}
        {msg && <div className="small">{msg}</div>}
      </div>

      <div className="card card-pad" style={{ marginTop: 12 }}>
        <div className="section-title">Recorded so far</div>
        <div className="small">{summary?.trips ?? 0} trips · control {summary?.by_variant?.control ?? 0} · sync {summary?.by_variant?.sync ?? 0} · gates {summary?.gates ?? 0}</div>
        <div className="small muted">Analyse with <span className="mono">python -m pipeline.field</span>; results appear on the Ops dashboard.</div>
      </div>
    </div>
  )
}
