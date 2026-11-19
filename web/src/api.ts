export type LatLon = [number, number]

export interface Gate {
  ap_id: string | null
  lat: number
  lon: number
  osm_gate: boolean
  gate_name?: string | null
  trips?: number
  agreement?: number
  confidence?: string
  faster_than_alternatives?: boolean
  median_handover_s?: number | null
  source?: string
  road?: string | null
}

export interface SiteRow {
  site_id: string
  name: string
  kind: string
  lat: number
  lon: number
  polygon: LatLon[]
  trips: number
  confidence: 'high' | 'medium' | 'low' | 'none'
  handover_type: string | null
  show_gate_hint: boolean
  show_sync: boolean
  gate: Gate | null
  gate_night: Gate | null
  parking: { lat: number; lon: number; trips: number; snapped_to_osm_parking: boolean } | null
  handover_median_s: number | null
  n_access_points: number
  n_osm_gates: number
  towers: number
  cold_start: boolean
}

export interface Tower {
  tower_id: string
  lat: number
  lon: number
  levels: number | null
  entrance: LatLon
  name?: string | null
}

export interface AccessPoint {
  ap_id: string
  lat: number
  lon: number
  osm_gate: boolean
  gate_osm_id: number | null
  gate_name: string | null
  drivable: boolean
}

export interface SiteDetail {
  site: { site_id: string; name: string; kind: string; polygon: LatLon[]; access_points: AccessPoint[]; towers: Tower[] }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  profile: any
}

export interface OrderEvent {
  t: number
  kind: string
  text: string
  rider_wait_s?: number
}

export interface OrderSnap {
  order_id: string
  phase: string
  sim_t: number
  rider: LatLon
  eta_s: number | null
  site: { site_id: string; name: string; kind: string; polygon: LatLon[]; access_points: AccessPoint[] }
  tower: Tower
  pin: LatLon
  route: LatLon[]
  gate: Gate
  parking: LatLon
  handover_point: LatLon
  handover_type: string
  lead_s: number | null
  lead_explain: string
  sync_enabled: boolean
  notified_at: number | null
  reply: 'coming' | 'security' | 'later2' | null
  reply_at: number | null
  customer_at_hp_at: number | null
  rider_at_hp_at: number | null
  delivered_at: number | null
  new_partner: boolean
  profile: {
    confidence: string | null
    trips: number | null
    gate_conf: string | null
    gate_agreement: number | null
    handover: { type?: string; confidence?: string; agreement?: number }
    handover_median_s: number | null
    handover_p80_s: number | null
    night_gate: boolean
    parking: { lat: number; lon: number } | null
    show_gate_hint: boolean | null
    show_sync: boolean | null
  }
  events: OrderEvent[]
  fair: { handover_s: number | null; rider_wait_s: number; building_p80_s: number | null; excuse_lateness: boolean; evidence: string[];
    evidence_codes?: { code: string; handover_s?: number; p80_s?: number; late_s?: number }[] } | null
  manual: boolean
  pickup: { name: string; kind: string; cuisine?: string | null; lat: number; lon: number; road?: string | null } | null
  route_pickup: LatLon[]
  accepted_at: number | null
  reached_pickup_at: number | null
  picked_up_at: number | null
  arrived_at: number | null
  called_at: number | null
  calls: number
  helped: boolean | null
  drop_distance_m: number
  delivered_ago_s: number | null
  inside_route: LatLon[]
  block: { name: string | null; levels: number | null; walk_m: number | null; mapped: boolean; door_learned: boolean; door_trips: number; index: number } | null
}

export interface Checkout {
  banner: string | null
  handover_type: string | null
  confidence: string
  eta_min: number
  eta_building_add_min: number
  pin_fix: { reason: string; suggest: { lat: number; lon: number; tower_id: string | null } } | null
  lead_s: number | null
  lead_explain: string
}

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json() as Promise<T>
}

export const api = {
  sites: () => fetch('/api/sites').then(j<SiteRow[]>),
  site: (id: string) => fetch(`/api/sites/${id}/profile`).then(j<SiteDetail>),
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  meta: () => fetch('/api/meta').then(j<any>),
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  metrics: () => fetch('/api/metrics').then(j<any>),
  checkout: (body: { site_id: string; tower_id?: string; pin_lat?: number; pin_lon?: number }) =>
    fetch('/api/checkout', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }).then(j<Checkout>),
  order: (body: Record<string, unknown>) =>
    fetch('/api/orders', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }).then(j<OrderSnap>),
  reply: (id: string, choice: string) =>
    fetch(`/api/orders/${id}/reply`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ choice }) }).then(j),
  action: (id: string, action: string) =>
    fetch(`/api/orders/${id}/action`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ action }) }).then(j<OrderSnap>),
  latest: () => fetch('/api/orders/latest').then(j<OrderSnap>),
  here: (id: string) => fetch(`/api/orders/${id}/customer-here`, { method: 'POST' }).then(j),
  helped: (id: string, helped: boolean) =>
    fetch(`/api/orders/${id}/helped`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ helped }) }).then(j),
  trialTrip: (body: unknown) =>
    fetch('/api/trial/trips', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }).then(j),
  trialGate: (body: unknown) =>
    fetch('/api/trial/gates', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }).then(j),
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  trialSummary: () => fetch('/api/trial/summary').then(j<any>),
}

export function subscribe(orderId: string, onSnap: (s: OrderSnap) => void): () => void {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  let ws: WebSocket | null = null
  let closed = false
  const open = () => {
    ws = new WebSocket(`${proto}://${location.host}/ws/orders/${orderId}`)
    ws.onmessage = (e) => onSnap(JSON.parse(e.data))
    ws.onclose = () => { if (!closed) setTimeout(open, 800) }
  }
  open()
  return () => { closed = true; ws?.close() }
}

export const fmtMin = (s: number | null | undefined) =>
  s == null ? '—' : s < 60 ? `${Math.round(s)} s` : `${(s / 60).toFixed(1)} min`

export const typeLabel: Record<string, string> = { lobby: 'Lobby handover', gate: 'Gate handover', doorstep: 'Doorstep' }
