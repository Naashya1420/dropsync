import { useEffect } from 'react'
import { CircleMarker, MapContainer, Polygon, Polyline, TileLayer, Tooltip, useMap } from 'react-leaflet'
import type { LatLon, OrderSnap } from '../api'

function Fit({ bounds }: { bounds: LatLon[] }) {
  const map = useMap()
  const key = bounds.map((b) => b.join(',')).join('|')
  useEffect(() => {
    if (bounds.length) map.fitBounds(bounds, { padding: [30, 30] })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return null
}

export function OsmTiles() {
  return (
    <TileLayer
      attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
      maxZoom={19}
    />
  )
}

export default function OrderMap({ snap, className, home }: { snap: OrderSnap | null; className?: string; home?: LatLon[] }) {
  const css = getComputedStyle(document.documentElement)
  const accent = css.getPropertyValue('--accent').trim() || '#c62839'
  const info = css.getPropertyValue('--info').trim() || '#24589c'
  const good = css.getPropertyValue('--good').trim() || '#1f7a4d'
  const center: LatLon = snap ? snap.rider : home?.[0] ?? [12.978, 77.717]
  const bounds: LatLon[] = snap ? [...snap.site.polygon, snap.route[0]] : home ?? []
  return (
    <MapContainer center={center} zoom={16} className={className} scrollWheelZoom={false}>
      <OsmTiles />
      <Fit bounds={bounds} />
      {!snap && home && <Polygon positions={home} pathOptions={{ color: info, weight: 2, fillOpacity: 0.08 }} />}
      {snap && (
        <>
          <Polygon positions={snap.site.polygon} pathOptions={{ color: info, weight: 2, fillOpacity: 0.08 }} />
          {snap.site.access_points.map((a) => (
            <CircleMarker key={a.ap_id} center={[a.lat, a.lon]} radius={4}
              pathOptions={{ color: a.osm_gate ? info : '#888', fillOpacity: 0.9, weight: 1 }}>
              <Tooltip>{a.osm_gate ? `OSM gate${a.gate_name ? ': ' + a.gate_name : ''}` : 'road/path entry (no gate tag)'}</Tooltip>
            </CircleMarker>
          ))}
          <Polyline positions={snap.route} pathOptions={{ color: accent, weight: 4, opacity: 0.55, dashArray: '6 6' }} />
          <CircleMarker center={[snap.gate.lat, snap.gate.lon]} radius={9}
            pathOptions={{ color: accent, fillColor: accent, fillOpacity: 0.9 }}>
            <Tooltip permanent direction="top" className="map-label">
              {snap.gate.source === 'learned' ? 'Rider gate (learned)' : 'Gate (navigation)'}
            </Tooltip>
          </CircleMarker>
          <CircleMarker center={snap.parking} radius={6} pathOptions={{ color: '#555', fillColor: '#fff', fillOpacity: 1, weight: 2 }}>
            <Tooltip>Parking point</Tooltip>
          </CircleMarker>
          <CircleMarker center={snap.handover_point} radius={8} pathOptions={{ color: good, fillColor: good, fillOpacity: 0.85 }}>
            <Tooltip permanent direction="bottom" className="map-label">Handover: {snap.handover_type}</Tooltip>
          </CircleMarker>
          <CircleMarker center={snap.pin} radius={5} pathOptions={{ color: '#7a3cc2', fillColor: '#7a3cc2', fillOpacity: 0.8 }}>
            <Tooltip>Customer pin</Tooltip>
          </CircleMarker>
          <CircleMarker center={snap.rider} radius={10} pathOptions={{ color: '#fff', weight: 3, fillColor: accent, fillOpacity: 1 }}>
            <Tooltip permanent direction="right" className="map-label">Rider</Tooltip>
          </CircleMarker>
        </>
      )}
    </MapContainer>
  )
}
