import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import Icon from '../components/Icon'
import { PersonaAvatar } from '../components/Avatar'
import { CURRENT_WEEK, KEY_IDEAS, PERSONAS, SUBJECTS, TOTAL_WEEKS, materialsFor } from '../data/mockData'

const MATERIAL_ICONS = {
  video: { icon: 'video', tone: 'violet' },
  slides: { icon: 'slides', tone: 'amber' },
  reading: { icon: 'book', tone: 'teal' },
  file: { icon: 'file', tone: 'grey' },
}

export default function Setup() {
  const navigate = useNavigate()
  const initial = useLocation().state || {}

  const [subjectId, setSubjectId] = useState(initial.subjectId || 'ds201')
  const [mode, setMode] = useState(initial.mode || 'single') // 'single' | 'range'
  const [week, setWeek] = useState(initial.week || CURRENT_WEEK)
  const [persona, setPersona] = useState(initial.persona || 'pip')
  const [input, setInput] = useState('voice')
  const [length, setLength] = useState(15)
  const [excluded, setExcluded] = useState({}) // material id -> true when unticked

  const subject = SUBJECTS.find((s) => s.id === subjectId)
  const materials = materialsFor(subject, week, mode)
  const isIncluded = (m) => (m.id in excluded ? !excluded[m.id] : !m.off)
  const includedCount = materials.filter(isIncluded).length

  const ideas =
    mode === 'range' && week > 1
      ? subject.topics.slice(0, week)
      : KEY_IDEAS[`${subjectId}-${week}`] || [subject.topics[week - 1]]

  const rangeLabel =
    mode === 'single' || week === 1
      ? `Week ${week} · ${subject.topics[week - 1]}`
      : `Weeks 1–${week} · mixed revision across ${week} weeks of material`

  const start = () =>
    navigate('/session', { state: { subjectId, week, mode, persona, input, length } })

  return (
    <div className="container gap-28">
      <div className="stack gap-10">
        <nav className="crumbs" aria-label="Breadcrumb">
          <Link to="/">Home</Link>
          <Icon name="chevronRight" size={14} stroke={2} />
          <span aria-current="page">New teaching session</span>
        </nav>
        <h1 className="page-title">What will you teach today?</h1>
      </div>

      <div className="subject-tabs" role="group" aria-label="Subject">
        {SUBJECTS.map((s) => (
          <button
            key={s.id}
            type="button"
            aria-pressed={s.id === subjectId}
            onClick={() => {
              setSubjectId(s.id)
              setExcluded({})
            }}
          >
            <span className="subject-tabs__code">{s.code}</span>
            {s.name}
          </button>
        ))}
      </div>

      <div className="split">
        <div className="split__main">
          <section className="card stack gap-20">
            <div className="row-between wrap gap-12">
              <h2 className="step-title">
                <span className="step-num">1</span>Choose the weeks
              </h2>
              <div className="segmented" role="group" aria-label="Scope">
                <button type="button" aria-pressed={mode === 'single'} onClick={() => setMode('single')}>
                  Just one week
                </button>
                <button type="button" aria-pressed={mode === 'range'} onClick={() => setMode('range')}>
                  Everything up to a week
                </button>
              </div>
            </div>

            <div className="week-grid">
              {Array.from({ length: TOTAL_WEEKS }, (_, i) => i + 1).map((n) => {
                const locked = n > CURRENT_WEEK
                const selected = n === week
                const inRange = mode === 'range' && n < week
                return (
                  <button
                    key={n}
                    type="button"
                    disabled={locked}
                    aria-pressed={selected}
                    aria-label={`Week ${n}${locked ? ', not released yet' : ''}`}
                    className={`week-btn${selected ? ' is-selected' : ''}${inRange ? ' is-range' : ''}`}
                    onClick={() => setWeek(n)}
                  >
                    <small>{locked ? 'SOON' : 'WEEK'}</small>
                    {n}
                  </button>
                )
              })}
            </div>

            <div className="info-bar">
              <Icon name="info" size={20} style={{ color: 'var(--violet)' }} />
              {rangeLabel}
            </div>
          </section>

          <section className="card stack gap-16">
            <div className="row-between wrap gap-8">
              <h2 className="card-title">Material from Canvas</h2>
              <span className="included">
                <span className="status-dot status-dot--teal" />
                {includedCount} of {materials.length} included
              </span>
            </div>

            {materials.map((m) => {
              const { icon, tone } = MATERIAL_ICONS[m.kind]
              return (
                <label className="material" key={m.id}>
                  <input
                    type="checkbox"
                    checked={isIncluded(m)}
                    onChange={() => setExcluded((ex) => ({ ...ex, [m.id]: isIncluded(m) }))}
                  />
                  <span className={`material__icon material__icon--${tone}`}>
                    <Icon name={icon} size={22} />
                  </span>
                  <span className="material__text">
                    <span className="material__title">{m.title}</span>
                    <span className="material__sub">{m.sub}</span>
                  </span>
                </label>
              )
            })}

            <div className="stack gap-10" style={{ marginTop: 6 }}>
              <span className="label-muted">
                {mode === 'range' && week > 1 ? 'Topics your student will mix together' : 'Key ideas your student will ask about'}
              </span>
              <div className="chips">
                {ideas.map((idea) => (
                  <span className="chip" key={idea}>
                    {idea}
                  </span>
                ))}
              </div>
            </div>
          </section>
        </div>

        <div className="split__side">
          <section className="card stack gap-14">
            <h2 className="step-title">
              <span className="step-num">2</span>Pick your student
            </h2>
            {Object.values(PERSONAS).map((p) => (
              <button
                key={p.id}
                type="button"
                className="persona"
                aria-pressed={persona === p.id}
                onClick={() => setPersona(p.id)}
              >
                <PersonaAvatar id={p.id} size={64} />
                <span className="persona__text">
                  <span className="persona__name">
                    {p.name} <span className="persona__kind">· {p.kind}</span>
                  </span>
                  <span className="persona__desc">{p.desc}</span>
                </span>
              </button>
            ))}
          </section>

          <section className="card stack gap-16">
            <h2 className="step-title">
              <span className="step-num">3</span>How will you teach?
            </h2>
            <div className="toggle-grid" role="group" aria-label="Teaching mode">
              <button type="button" className="toggle" aria-pressed={input === 'voice'} onClick={() => setInput('voice')}>
                <Icon name="mic" /> Out loud
              </button>
              <button type="button" className="toggle" aria-pressed={input === 'text'} onClick={() => setInput('text')}>
                <Icon name="keyboard" /> Typing
              </button>
            </div>
            <div className="row-between wrap gap-10">
              <span className="label-muted">Session length</span>
              <div className="row gap-6" role="group" aria-label="Session length">
                {[10, 15, 25].map((v) => (
                  <button key={v} type="button" className="len-btn" aria-pressed={length === v} onClick={() => setLength(v)}>
                    {v} min
                  </button>
                ))}
              </div>
            </div>
          </section>

          <button type="button" className="btn btn--violet btn--xl" onClick={start} disabled={includedCount === 0}>
            Start teaching {PERSONAS[persona].name}
            <Icon name="arrowRight" size={22} stroke={2} />
          </button>
          <p className="fine-print center">
            {includedCount === 0
              ? 'Tick at least one Canvas file so your student has something to learn from.'
              : `${PERSONAS[persona].name} only knows what's in your Canvas material, so they can't bluff, and neither can you.`}
          </p>
        </div>
      </div>
    </div>
  )
}
