import { NavLink, Route, Routes } from 'react-router-dom'
import Demo from './pages/Demo'
import Ops from './pages/Ops'
import Trial from './pages/Trial'
import RiderApp from './rider/RiderApp'
import Stage from './rider/Stage'
import Track from './rider/Track'

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="shell">
      <header className="topbar">
        <NavLink to="/" className="brand"><span className="brand-mark">D</span>DropSync <small>last-100-m handover sync</small></NavLink>
        <nav className="nav">
          <NavLink to="/stage">Rider app</NavLink>
          <NavLink to="/" end>Live demo</NavLink>
          <NavLink to="/ops">Ops dashboard</NavLink>
          <NavLink to="/trial">Field trial</NavLink>
        </nav>
        <div className="spacer" />
      </header>
      {children}
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      {/* full-screen phone apps (no site chrome) */}
      <Route path="/rider" element={<RiderApp />} />
      <Route path="/track" element={<Track />} />
      <Route path="/stage" element={<Stage />} />
      <Route path="/" element={<Shell><Demo /></Shell>} />
      <Route path="/ops" element={<Shell><Ops /></Shell>} />
      <Route path="/trial" element={<Shell><Trial /></Shell>} />
    </Routes>
  )
}
