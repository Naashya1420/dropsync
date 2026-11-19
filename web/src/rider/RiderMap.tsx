import { useEffect, useRef } from 'react'
import L from 'leaflet'
import { CircleMarker, MapContainer, Marker, Polygon, Polyline, Tooltip, useMap } from 'react-leaflet'
import type { LatLon, OrderSnap } from '../api'
import { OsmTiles } from '../components/OrderMap'
import { forkSvg, homeSvg, scooterSvg } from './icons'

// black round markers with white glyphs, as in the partner app's order map
const glyph = (svg: string, extra = '') =>
  L.divIcon({ className: '', html: `<div class="zmark ${extra}">${svg}</div>`, iconSize: [32, 32], iconAnchor: [16, 16] })
const riderIcon = glyph(scooterSvg, 'rider')
const pickIcon = glyph(forkSvg)
const dropIcon = glyph(homeSvg)

const DROP_PHASES = ['to_gate', 'gate_check', 'parking', 'walk', 'at_handover', 'indoors', 'delivered']
const AT_SITE = ['gate_check', 'parking', 'walk', 'at_handover', 'indoors']

/** Quadratic curve between two points, for the dotted preview line on the offer screen. */
function curve(a: LatLon, b: LatLon): LatLon[] {
  const mid: LatLon = [(a[0] + b[0]) / 2 + (b[1] - a[1]) * 0.25, (a[1] + b[1]) / 2 - (b[0] - a[0]) * 0.25]
  const pts: LatLon[] = []
  for (let i = 0; i <= 24; i++) {
    const t = i / 24
    pts.push([(1 - t) ** 2 * a[0] + 2 * (1 - t) * t * mid[0] + t * t * b[0], (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * mid[1] + t * t * b[1]])
  }
  return pts
}

function Follow({ snap, home, bottomFrac }: { snap: OrderSnap | null; home: LatLon; bottomFrac: number }) {
  const map = useMap()
  const last = useRef('')
  const area = useRef<LatLon[] | null>(null)

  // keep everything above the bottom card, using the card's real (current) height
  const fit = (pts: LatLon[]) => {
    map.invalidateSize()
    const sheet = document.querySelector('.zsheet') as HTMLElement | null
    const below = sheet ? sheet.getBoundingClientRect().height : map.getSize().y * bottomFrac
    map.fitBounds(L.latLngBounds(pts), {
      paddingTopLeft: [36, 70], paddingBottomRight: [36, Math.round(below) + 28], maxZoom: 17,
    })
  }

  useEffect(() => {
    if (!snap) {
      area.current = null
      if (last.current !== 'home') { map.setView(home, 15); last.current = 'home' }
      return
    }
    const leg = snap.phase === 'offered' ? 'offer' : DROP_PHASES.includes(snap.phase) ? (AT_SITE.includes(snap.phase) ? 'site' : 'drop') : 'pickup'
    const key = snap.order_id + leg
    if (key === last.current) return
    last.current = key
    let pts: LatLon[]
    if (leg === 'offer') pts = [snap.rider, snap.pickup ? [snap.pickup.lat, snap.pickup.lon] : snap.route[0]]
    else if (leg === 'site') pts = [...snap.site.polygon, snap.rider]
    else if (leg === 'drop') pts = [...snap.route, ...snap.site.polygon]
    else pts = snap.route_pickup.length ? snap.route_pickup : snap.route
    area.current = pts
    fit(pts)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snap, map, home, bottomFrac])

  // the card's height settles after fonts/content load and changes between stages:
  // refit the current area whenever it changes noticeably
  useEffect(() => {
    const sheet = document.querySelector('.zsheet')
    if (!sheet || typeof ResizeObserver === 'undefined') return
    let h = sheet.getBoundingClientRect().height
    const ro = new ResizeObserver(() => {
      const nh = sheet.getBoundingClientRect().height
      if (Math.abs(nh - h) > 16 && area.current) { h = nh; fit(area.current) }
    })
    ro.observe(sheet)
    return () => ro.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snap?.order_id, map])
  return null
}

export default function RiderMap({ snap, home, bottomFrac, dark = false }: { snap: OrderSnap | null; home: LatLon; bottomFrac: number; dark?: boolean }) {
  const ink = dark ? '#f1f1f1' : '#111'  // route lines must stay visible on the dimmed dark map
  const offer = snap?.phase === 'offered'
  const drop = snap ? DROP_PHASES.includes(snap.phase) : false
  const pick: LatLon | null = snap?.pickup ? [snap.pickup.lat, snap.pickup.lon] : null
  return (
    <MapContainer center={home} zoom={15} className="zmap" zoomControl={false}>
      <OsmTiles />
      <Follow snap={snap} home={home} bottomFrac={bottomFrac} />
      {snap && (
        <>
          {offer && pick && <Polyline positions={curve(snap.rider, pick)} pathOptions={{ color: ink, weight: 3, dashArray: '2 8', lineCap: 'round' }} />}
          {!offer && !drop && snap.route_pickup.length > 0 && <Polyline positions={snap.route_pickup} pathOptions={{ color: ink, weight: 5, opacity: 0.85 }} />}
          {drop && <Polyline positions={snap.route} pathOptions={{ color: ink, weight: 5, opacity: 0.85 }} />}
          {pick && !drop && <Marker position={pick} icon={pickIcon} />}
          {drop && (
            <>
              <Polygon positions={snap.site.polygon} pathOptions={{ color: '#2563eb', weight: 2, fillOpacity: 0.08 }} />
              {snap.gate.source === 'learned' && (
                <CircleMarker center={[snap.gate.lat, snap.gate.lon]} radius={9} pathOptions={{ color: '#fff', weight: 3, fillColor: '#16a34a', fillOpacity: 1 }}>
                  <Tooltip permanent direction="top" className="map-label">Rider gate</Tooltip>
                </CircleMarker>
              )}
              {snap.profile.parking && (
                <CircleMarker center={snap.parking} radius={7} pathOptions={{ color: '#111', weight: 2, fillColor: '#fff', fillOpacity: 1 }}>
                  <Tooltip direction="left" className="map-label">P</Tooltip>
                </CircleMarker>
              )}
              {snap.inside_route?.length > 1 && (
                <Polyline positions={snap.inside_route} pathOptions={{ color: '#2563eb', weight: 4, dashArray: '1 7', lineCap: 'round' }} />
              )}
              <Marker position={snap.handover_point} icon={dropIcon} />
            </>
          )}
          <Marker position={snap.rider} icon={riderIcon} zIndexOffset={1000} />
        </>
      )}
    </MapContainer>
  )
}
