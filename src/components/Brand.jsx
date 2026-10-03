export default function Brand({ tagline = true }) {
  return (
    <div className="brand">
      <div className="brand__mark" aria-hidden="true">
        <svg width="26" height="26" viewBox="0 0 26 26">
          <circle cx="9" cy="11" r="2.4" fill="#15161B" />
          <circle cx="17" cy="11" r="2.4" fill="#15161B" />
          <path d="M9 16.5 Q13 20 17 16.5" stroke="#15161B" strokeWidth="2.2" fill="none" strokeLinecap="round" />
        </svg>
      </div>
      <div>
        <div className="brand__name">Pupil</div>
        {tagline && <div className="brand__tag">learn by teaching</div>}
      </div>
    </div>
  )
}
