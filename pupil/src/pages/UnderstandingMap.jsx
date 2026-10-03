import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import Icon from '../components/Icon'
import StatusIcon from '../components/StatusIcon'
import { PersonaAvatar } from '../components/Avatar'
import {
  MAP_ISSUES,
  MAP_LINES,
  MAP_NODES,
  MAP_ROOT,
  PERSONAS,
  SEMESTER,
  TOUGHEST_QUESTION,
} from '../data/mockData'

const NODE_STATE = {
  E: 'Explained well',
  S: 'Shaky',
  G: "Couldn't explain",
  N: "Didn't come up",
}

const SEM_LABELS = { E: 'Solid', S: 'Shaky', G: '1 gap', T: 'Today', U: 'Soon' }

export default function UnderstandingMap() {
  const state = useLocation().state || {}
  const persona = PERSONAS[state.persona || 'pip']
  const [selectedId, setSelectedId] = useState('oa')
  const selected = MAP_NODES.find((n) => n.id === selectedId)

  const counts = MAP_NODES.reduce((acc, n) => ({ ...acc, [n.status]: (acc[n.status] || 0) + 1 }), {})
  const scoreBar = [
    ...Array(counts.E || 0).fill('E'),
    ...Array(counts.S || 0).fill('S'),
    ...Array(counts.G || 0).fill('G'),
    ...Array(counts.N || 0).fill('N'),
  ]

  return (
    <div className="container gap-24">
      <header className="page-head">
        <div className="stack gap-10">
          <span className="pill pill--lime">
            <Icon name="check" size={14} stroke={3} />
            Session complete · 18 min with {persona.name}
          </span>
          <h1 className="page-title">Here's what {persona.name} learned from you.</h1>
          <p className="lede">Data Structures · Week 6 · Hash tables and collisions</p>
        </div>
        <div className="row wrap gap-10">
          <button type="button" className="btn btn--ghost">
            <Icon name="share" size={18} /> Share with tutor
          </button>
          <button type="button" className="btn btn--ghost">
            <Icon name="download" size={18} /> Save as revision notes
          </button>
        </div>
      </header>

      <section className="card stack gap-20">
        <div className="row-between wrap gap-12">
          <h2 className="card-title">Your Understanding Map</h2>
          <div className="legend legend--lg">
            <span><StatusIcon status="E" size={18} />Explained well</span>
            <span><StatusIcon status="S" size={18} />Shaky</span>
            <span><StatusIcon status="G" size={18} />Couldn't explain</span>
            <span><StatusIcon status="N" size={18} />Didn't come up</span>
          </div>
        </div>

        <div className="tree-wrap">
          <div className="tree">
            {MAP_LINES.map(([left, top, width, height], i) => (
              <span key={i} className="tree__line" style={{ left, top, width, height }} />
            ))}
            <div className="node node--root" style={{ left: MAP_ROOT.x, top: MAP_ROOT.y }}>
              <span className="node--root__title">{MAP_ROOT.title}</span>
              <span className="node--root__sub">{MAP_ROOT.sub}</span>
            </div>
            {MAP_NODES.map((n) => (
              <button
                key={n.id}
                type="button"
                className={`node node--${n.status}${selectedId === n.id ? ' is-selected' : ''}`}
                style={{ left: n.x, top: n.y }}
                onClick={() => setSelectedId(n.id)}
                aria-pressed={selectedId === n.id}
              >
                <StatusIcon status={n.status} size={26} />
                <span>
                  <span className="node__title">{n.title}</span>
                  <span className={`node__state node__state--${n.status}`}>{NODE_STATE[n.status]}</span>
                </span>
              </button>
            ))}
          </div>
        </div>

        {selected && (
          <div className={`node-detail node-detail--${selected.status}`} aria-live="polite">
            <StatusIcon status={selected.status} size={32} square />
            <div className="stack gap-4">
              <strong>{selected.title}</strong>
              <span>{selected.note}</span>
            </div>
            {selected.time && (
              <Link to="/session" state={{ persona: persona.id }} className="btn btn--ghost">
                <Icon name="play" size={14} /> Replay {selected.time}
              </Link>
            )}
          </div>
        )}
      </section>

      <div className="row-wrap gap-20 align-stretch">
        <section className="card breakdown stack gap-14">
          <h2 className="card-title card-title--md">Where your explanation broke down</h2>
          {MAP_ISSUES.map((issue) => (
            <div className={`issue issue--${issue.status}`} key={issue.title}>
              <StatusIcon status={issue.status} size={32} square />
              <div className="stack gap-6">
                <strong>{issue.title}</strong>
                <span className="issue__text">{issue.text}</span>
                <Link to="/session" state={{ persona: persona.id }} className="link-strong small-text">
                  Replay the moment · {issue.time}
                </Link>
              </div>
            </div>
          ))}
        </section>

        <section className="map-side stack gap-20">
          <div className="score-card">
            <span className="small-text" style={{ color: 'var(--nav-text)', fontWeight: 600 }}>
              Ideas that landed
            </span>
            <span className="big-number">
              {(counts.E || 0) + 1} <span className="big-number__of">of {MAP_NODES.length + 1}</span>
            </span>
            <div className="score-bar">
              <span className="E" />
              {scoreBar.map((s, i) => (
                <span key={i} className={s} />
              ))}
            </div>
            <Link to="/session" state={{ persona: persona.id }} className="btn btn--lime btn--lg btn--block">
              Re-teach my 3 weak spots · ~6 min
            </Link>
            <Link to="/setup" state={{ persona: 'milo', subjectId: 'ds201', week: 6 }} className="btn btn--outline-dark btn--block">
              Try Milo on the same topic
            </Link>
          </div>

          <div className="quote-card">
            <PersonaAvatar id={persona.id} size={44} />
            <div className="stack gap-6">
              <span className="eyebrow eyebrow--ink">{persona.name.toUpperCase()}'S TOUGHEST QUESTION</span>
              <span className="quote-card__text">{TOUGHEST_QUESTION}</span>
            </div>
          </div>
        </section>
      </div>

      <section className="card stack gap-14">
        <div className="row-between wrap gap-8">
          <h2 className="card-title card-title--md">Data Structures across the semester</h2>
          <span className="small-text muted">Weeks 7–12 unlock as they're released on Canvas</span>
        </div>
        <div className="sem">
          {SEMESTER.split('').map((c, i) => (
            <div key={i} className={`sem__cell sem__cell--${c}`}>
              <span className="sem__week">WEEK</span>
              <span className="sem__num">{i + 1}</span>
              <span className="sem__label">{SEM_LABELS[c]}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
