import { useState } from 'react'
import { Link } from 'react-router-dom'
import Icon from '../components/Icon'
import StatusIcon from '../components/StatusIcon'
import { PersonaAvatar } from '../components/Avatar'
import { useAuth } from '../auth'
import { CURRENT_WEEK, GAPS, PERSONAS, STATUS_LABELS, STREAK, SUBJECTS } from '../data/mockData'

function greeting() {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 17) return 'Good afternoon'
  return 'Good evening'
}

function SyncButton() {
  const [state, setState] = useState('idle') // idle | syncing | done
  const sync = () => {
    setState('syncing')
    setTimeout(() => setState('done'), 1200)
  }
  return (
    <button type="button" className="btn btn--ghost" onClick={sync} disabled={state === 'syncing'}>
      <Icon name={state === 'done' ? 'check' : 'sync'} size={18} className={state === 'syncing' ? 'spin' : undefined} />
      {state === 'syncing' ? 'Syncing…' : state === 'done' ? 'Synced just now' : 'Sync from Canvas'}
    </button>
  )
}

export default function Home() {
  const { user } = useAuth()
  const firstName = user?.name?.split(' ')[0] || 'there'

  return (
    <div className="container">
      <header className="page-head">
        <div className="stack gap-10">
          <span className="pill">Semester 2 · Week {CURRENT_WEEK}</span>
          <h1 className="page-title">
            {greeting()}, {firstName}.
          </h1>
          <p className="lede">Your students have been reading this week's Canvas material. They're confused. Time to teach them.</p>
        </div>
        <div className="row gap-12">
          <SyncButton />
          <span className="avatar-initial" role="img" aria-label={`${user?.name}'s profile`}>
            {firstName[0]}
          </span>
        </div>
      </header>

      <section className="row-wrap gap-20">
        <div className="hero">
          <div className="hero__body">
            <span className="eyebrow">UP NEXT · DATA STRUCTURES</span>
            <h2 className="hero__title">Pip is stuck on hash tables.</h2>
            <p>
              Week 6 landed on Canvas yesterday: a 48-minute lectorial, slides and two textbook chapters. Pip read all of
              it and has questions only you can answer.
            </p>
            <div className="hero__actions">
              <Link to="/setup" state={{ subjectId: 'ds201', week: 6 }} className="btn btn--lime btn--lg">
                Start teaching Week 6 <Icon name="arrowRight" size={18} stroke={2} />
              </Link>
              <Link to="/setup" state={{ subjectId: 'ds201', mode: 'range', week: 6 }} className="btn btn--outline-light btn--lg">
                Pick other weeks
              </Link>
            </div>
          </div>
          <div className="hero__pip">
            <div className="bubble">Wait… what happens when two keys want the same box?</div>
            <div className="bob">
              <PersonaAvatar id="pip" size={150} onDark label="Pip, the curious student" />
            </div>
          </div>
        </div>

        <div className="card stat-card">
          <div className="stack gap-8">
            <span className="label-muted">Teaching streak</span>
            <span className="big-number">5 days</span>
            <div className="streak">
              {STREAK.map((d, i) => (
                <div className="streak__day" key={i}>
                  <span className={`streak__dot streak__dot--${d.state}`} />
                  {d.label}
                </div>
              ))}
            </div>
          </div>
          <div className="divider" />
          <div className="stack gap-10">
            <div className="row-between">
              <span className="label-muted">Ideas you can explain</span>
              <strong>34 / 58</strong>
            </div>
            <div className="progress" role="progressbar" aria-valuenow={34} aria-valuemin={0} aria-valuemax={58} aria-label="Ideas you can explain">
              <span style={{ width: '59%' }} />
            </div>
          </div>
          <div className="callout">
            <Icon name="calendar" size={22} style={{ color: 'var(--violet)' }} />
            <div>
              <strong>Quiz 3 on Thursday</strong>
              <br />
              <span className="muted">Covers Weeks 4–6 · from Canvas</span>
            </div>
          </div>
        </div>
      </section>

      <section className="stack gap-16">
        <div className="section-head">
          <h2 className="section-title">Your subjects</h2>
          <div className="legend">
            <span><i className="swatch wk--E" />Explained well</span>
            <span><i className="swatch wk--S" />Shaky</span>
            <span><i className="swatch wk--G" />Gap found</span>
            <span><i className="swatch wk--N" />Not taught yet</span>
          </div>
        </div>
        <div className="grid-cards">
          {SUBJECTS.map((s) => (
            <article className="subject" key={s.id}>
              <div className="row-between">
                <span className="code">{s.code}</span>
                <span className={`badge badge--${s.badge.tone}`}>{s.badge.label}</span>
              </div>
              <h3 className="subject__name">{s.name}</h3>
              <div>
                <div className="weekstrip">
                  {s.progress.split('').map((c, i) => (
                    <span key={i} className={`wk wk--${c}`} title={`Week ${i + 1}: ${STATUS_LABELS[c]}`} />
                  ))}
                </div>
                <div className="weekstrip__axis">
                  <span>Wk 1</span>
                  <span>Wk 12</span>
                </div>
              </div>
              <div className="meta">
                <Icon name="video" size={16} />
                {s.materialsSummary}
              </div>
              <Link
                to="/setup"
                state={{ subjectId: s.id, week: CURRENT_WEEK, mode: s.badge.tone === 'ok' ? 'range' : 'single' }}
                className="btn btn--dark btn--block"
              >
                {s.cta}
              </Link>
            </article>
          ))}
        </div>
      </section>

      <section className="row-wrap gap-20">
        <div className="card gaps-card">
          <h2 className="card-title">Gaps your students caught</h2>
          {GAPS.map((g) => {
            const subject = SUBJECTS.find((s) => s.id === g.subjectId)
            return (
              <div className="gap-row" key={g.concept}>
                <StatusIcon status={g.status} size={36} square />
                <div className="gap-row__body">
                  <div className="gap-row__title">{g.concept}</div>
                  <div className="gap-row__sub">
                    {subject.name} · Week {g.week} · caught by {PERSONAS[g.persona].name}
                  </div>
                </div>
                <span className={`badge badge--${g.status === 'G' ? 'gap' : 'shaky'}`}>{g.status === 'G' ? 'Gap' : 'Shaky'}</span>
                <Link to="/session" state={{ subjectId: g.subjectId, week: g.week, persona: g.persona }} className="link-strong">
                  Re-teach
                </Link>
              </div>
            )
          })}
        </div>

        <div className="how">
          <h2 className="card-title">How Pupil works</h2>
          {[
            ['Pick a week', 'Lectorials, slides and readings come straight from Canvas.'],
            ['Teach a confused student', "Explain it out loud. They push back where you're vague."],
            ['See your map', 'Find out what you really understand before the exam does.'],
          ].map(([title, text], i) => (
            <div className="how__step" key={title}>
              <span className="how__num">{i + 1}</span>
              <div>
                <strong>{title}</strong>
                <br />
                {text}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
