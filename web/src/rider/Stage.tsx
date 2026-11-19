/** Laptop presentation: only the two phones side by side (rider app + customer app).
 *  Each frame is the real /rider and /track page. */
export default function Stage() {
  return (
    <div className="stage only">
      <div className="stage-phone"><iframe title="Rider app" src="/rider" /></div>
      <div className="stage-phone"><iframe title="Customer app" src="/track" /></div>
    </div>
  )
}
