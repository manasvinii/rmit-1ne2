import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import Icon from '../components/Icon'
import StatusIcon from '../components/StatusIcon'
import { PersonaAvatar } from '../components/Avatar'
import {
  CURRENT_WEEK,
  DEMO_CONVERSATION,
  LIVE_DRAFT,
  NOTEBOOK,
  PERSONAS,
  PERSONA_REPLIES,
  SESSION_IDEAS,
  SLIDE_HINT,
  SUBJECTS,
} from '../data/mockData'

const WAVE = [6, 10, 16, 24, 14, 8, 18, 26, 20, 12, 6, 10, 22, 28, 18, 10, 14, 24, 16, 8, 6, 12, 20, 14, 10, 18, 26, 16, 8, 6, 10, 6]

function formatTime(total) {
  const m = Math.floor(total / 60)
  const s = String(total % 60).padStart(2, '0')
  return `${m}:${s}`
}

export default function Session() {
  const state = useLocation().state || {}
  const subject = SUBJECTS.find((s) => s.id === (state.subjectId || 'ds201'))
  const week = state.week || CURRENT_WEEK
  const persona = PERSONAS[state.persona || 'pip']
  const totalSeconds = (state.length || 15) * 60

  const [listening, setListening] = useState(state.input !== 'text')
  const [typingOpen, setTypingOpen] = useState(state.input === 'text')
  const [secondsLeft, setSecondsLeft] = useState(Math.max(totalSeconds - 200, 60))
  const [messages, setMessages] = useState(DEMO_CONVERSATION)
  const [draft, setDraft] = useState('')
  const [thinking, setThinking] = useState(false)

  const replyIndex = useRef(0)
  const logRef = useRef(null)
  const timers = useRef([])

  // Countdown
  useEffect(() => {
    const id = setInterval(() => setSecondsLeft((v) => Math.max(0, v - 1)), 1000)
    return () => clearInterval(id)
  }, [])

  // Clear pending fake replies on unmount
  useEffect(() => () => timers.current.forEach(clearTimeout), [])

  // Keep the newest message in view
  useEffect(() => {
    const el = logRef.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [messages, thinking, listening])

  const send = (e) => {
    e.preventDefault()
    const text = draft.trim()
    if (!text) return
    setMessages((m) => [...m, { from: 'me', via: 'text', meta: 'You, typed', text }])
    setDraft('')
    setThinking(true)
    // TODO: replace with a call to your AI backend
    const t = setTimeout(() => {
      const replies = PERSONA_REPLIES[persona.id]
      const reply = replies[replyIndex.current % replies.length]
      replyIndex.current += 1
      setMessages((m) => [...m, { from: 'student', text: reply }])
      setThinking(false)
    }, 1200)
    timers.current.push(t)
  }

  const showHint = () => setMessages((m) => [...m, { type: 'hint', text: SLIDE_HINT }])

  return (
    <div className="session">
      <header className="topbar">
        <div className="row gap-16">
          <Link to="/" className="icon-btn" aria-label="Leave session">
            <Icon name="arrowLeft" size={20} stroke={2} />
          </Link>
          <div>
            <div className="topbar__title">Teaching {persona.name}</div>
            <div className="topbar__sub">
              {subject.name} · Week {week} · {subject.topics[week - 1]}
            </div>
          </div>
        </div>
        <div className="row gap-12">
          <span className="timer" aria-label={`${formatTime(secondsLeft)} left`}>
            <Icon name="timer" size={18} stroke={2} />
            {formatTime(secondsLeft)} left
          </span>
          <Link to="/map" state={{ persona: persona.id, subjectId: subject.id, week }} className="btn btn--dark">
            End and see my map
          </Link>
        </div>
      </header>

      <div className="session__body">
        <aside className="session__left">
          <section className="card card--tight stack gap-4">
            <h2 className="card-title card-title--sm">Today's ideas</h2>
            {SESSION_IDEAS.map((idea) => {
              const current = idea.state === 'current'
              const todo = idea.state === 'todo'
              return (
                <div key={idea.name} className={`idea-row${current ? ' is-current' : ''}${todo ? ' is-todo' : ''}`}>
                  {current ? (
                    <span className="idea-row__now" aria-hidden="true">
                      <span />
                    </span>
                  ) : (
                    <StatusIcon status={todo ? 'N' : idea.state} size={26} />
                  )}
                  <span className="idea-row__name">{idea.name}</span>
                  {current && <span className="idea-row__state idea-row__state--now">Teaching now</span>}
                  {idea.state === 'E' && <span className="idea-row__state idea-row__state--good">Got it</span>}
                  {idea.state === 'S' && <span className="idea-row__state idea-row__state--shaky">Shaky</span>}
                </div>
              )
            })}
          </section>

          <section className="card card--tight stack gap-12">
            <h2 className="small-heading">FROM YOUR CANVAS MATERIAL</h2>
            <div className="slide-thumb" aria-hidden="true">
              <div className="slide-thumb__title" />
              <div className="slide-thumb__boxes">
                <span /><span className="on" /><span /><span className="on" /><span />
              </div>
              <div className="slide-thumb__line" />
            </div>
            <div className="small-text">
              <strong>Slide 14 · Handling collisions</strong>
              <br />
              <span className="muted">{persona.name}'s next question comes from here.</span>
            </div>
            <a href="#lectorial" className="link-strong row gap-8">
              <Icon name="play" size={16} />
              Lectorial at 23:10
            </a>
          </section>
        </aside>

        <section className="chat" aria-label="Conversation">
          <div className="chat__log" ref={logRef} aria-live="polite">
            {messages.map((m, i) => {
              if (m.type === 'flag')
                return (
                  <div className="flag" key={i}>
                    <StatusIcon status="S" size={20} />
                    {m.text.replace('{name}', persona.name)}
                  </div>
                )
              if (m.type === 'hint')
                return (
                  <div className="flag flag--hint" key={i}>
                    <Icon name="bulb" size={16} />
                    {m.text}
                  </div>
                )
              if (m.from === 'me')
                return (
                  <div className="msg msg--me" key={i}>
                    <div className="msg__bubble">{m.text}</div>
                    <span className="msg__meta">
                      <Icon name={m.via === 'voice' ? 'mic' : 'keyboard'} size={12} stroke={2.2} />
                      {m.meta}
                    </span>
                  </div>
                )
              return (
                <div className="msg" key={i}>
                  <PersonaAvatar id={persona.id} size={36} />
                  <div className="msg__bubble">{m.text}</div>
                </div>
              )
            })}

            {thinking && (
              <div className="msg">
                <PersonaAvatar id={persona.id} size={36} />
                <div className="msg__bubble typing" aria-label={`${persona.name} is thinking`}>
                  <span /><span /><span />
                </div>
              </div>
            )}

            {listening && !thinking && (
              <div className="msg msg--me msg--live">
                <div className="msg__bubble">
                  {LIVE_DRAFT}
                  <span className="caret" />
                </div>
                <span className="msg__meta">Transcribing…</span>
              </div>
            )}
          </div>

          <div className="composer">
            <button
              type="button"
              className={`mic${listening ? ' is-on' : ''}`}
              onClick={() => setListening((v) => !v)}
              aria-label={listening ? 'Pause microphone' : 'Start microphone'}
              aria-pressed={listening}
            >
              <Icon name="mic" size={30} stroke={2} />
            </button>
            <div className="composer__status">
              <span className="composer__label">
                {listening ? 'Listening… keep explaining' : 'Paused. Tap the mic to carry on'}
              </span>
              <div className={`wave${listening ? ' is-on' : ''}`} aria-hidden="true">
                {WAVE.map((h, i) => (
                  <span key={i} style={{ height: h, animationDelay: `${(i % 8) * 90}ms` }} />
                ))}
              </div>
            </div>
            <div className="row wrap gap-8">
              <button type="button" className="btn btn--ghost" title="Whiteboard coming soon">
                <Icon name="pen" size={18} /> Draw it
              </button>
              <button type="button" className="btn btn--ghost" onClick={showHint}>
                <Icon name="bulb" size={18} /> Hint from slides
              </button>
              <button
                type="button"
                className="btn btn--ghost"
                aria-pressed={typingOpen}
                onClick={() => setTypingOpen((v) => !v)}
              >
                <Icon name="keyboard" size={18} /> Type
              </button>
            </div>

            {typingOpen && (
              <form className="type-form" onSubmit={send}>
                <label htmlFor="explain" className="sr-only">
                  Explain it to {persona.name}
                </label>
                <input
                  id="explain"
                  className="input"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder={`Explain it to ${persona.name}…`}
                  autoFocus
                  autoComplete="off"
                />
                <button type="submit" className="btn btn--violet btn--lg" disabled={!draft.trim() || thinking}>
                  <Icon name="send" size={18} /> Send
                </button>
              </form>
            )}
          </div>
        </section>

        <aside className="session__right">
          <section className="persona-card">
            <div className="bob">
              <PersonaAvatar id={persona.id} size={140} mood="puzzled" onDark label={`${persona.name} looking puzzled`} />
            </div>
            <div>
              <div className="persona-card__name">{persona.name}</div>
              <div className="persona-card__kind">{persona.kind}</div>
            </div>
            <div className="persona-card__meter">
              <div className="row-between small-text">
                <span style={{ color: 'var(--nav-text)' }}>{persona.name}'s confusion</span>
                <span style={{ color: 'var(--amber-bar)' }}>Getting there</span>
              </div>
              <div className="meter">
                <span className="on" /><span className="on" /><span className="on" /><span /><span />
              </div>
              <div className="persona-card__hint">Bring it to zero to finish "Collisions".</div>
            </div>
          </section>

          <section className="notebook">
            <h2 className="small-heading">{persona.name.toUpperCase()}'S NOTEBOOK</h2>
            <p className="small-text muted">What actually got through to {persona.name}, in their own words.</p>
            <div className="notebook__lines">
              {NOTEBOOK.map((line) => (
                <span key={line.text} className={line.warn ? 'warn' : undefined}>
                  · {line.text}
                </span>
              ))}
            </div>
          </section>
        </aside>
      </div>
    </div>
  )
}
