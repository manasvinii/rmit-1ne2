import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import Brand from '../components/Brand'
import Icon from '../components/Icon'
import { PersonaAvatar } from '../components/Avatar'
import { useAuth } from '../auth'
import { DEMO_USER } from '../data/mockData'

function nameFromEmail(email) {
  const local = email.split('@')[0].replace(/[._-]+/g, ' ').trim()
  return local
    .split(' ')
    .filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(' ')
}

export default function Login() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [mode, setMode] = useState('signin') // 'signin' | 'signup'
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [remember, setRemember] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(null) // null | 'email' | 'canvas'

  if (user) return <Navigate to="/" replace />

  const destination = location.state?.from || '/'
  const isSignup = mode === 'signup'

  // Fake a short network delay so the button states are visible in the demo.
  const finish = (nextUser, how) => {
    setBusy(how)
    setTimeout(() => {
      login(nextUser, { remember })
      navigate(destination, { replace: true })
    }, 700)
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    if (isSignup && !name.trim()) return setError('Tell us your name so your students know who you are.')
    if (!/^\S+@\S+\.\S+$/.test(email)) return setError('Enter your university email address.')
    if (password.length < 6) return setError('Your password needs at least 6 characters.')
    setError('')
    finish({ name: isSignup ? name.trim() : nameFromEmail(email), email, via: 'email' }, 'email')
  }

  const switchMode = () => {
    setMode(isSignup ? 'signin' : 'signup')
    setError('')
  }

  return (
    <div className="login">
      <aside className="login__art">
        <Brand />

        <div className="login__stage" aria-hidden="true">
          <div className="float float--sage">
            <PersonaAvatar id="sage" size={84} />
            <div className="bubble bubble--sm">Prove it.</div>
          </div>
          <div className="login__pip">
            <div className="bubble">Wait… why does that happen?</div>
            <div className="bob">
              <PersonaAvatar id="pip" size={180} onDark />
            </div>
          </div>
          <div className="float float--milo">
            <div className="bubble bubble--sm">Isn't heavier stuff faster?</div>
            <PersonaAvatar id="milo" size={88} />
          </div>
        </div>

        <div className="login__copy">
          <h1 className="login__headline">
            Learn it by <mark>teaching</mark> it.
          </h1>
          <p className="login__lede">
            Pupil turns each week of your Canvas course into a student who needs your help. Explain it out loud, and
            find your gaps before the exam does.
          </p>
          <ul className="login__features">
            <li>
              <Icon name="sync" size={18} />
              Syncs your weekly lectorials, slides and readings
            </li>
            <li>
              <Icon name="mic" size={18} />
              Explain out loud to a student who keeps asking "why?"
            </li>
            <li>
              <Icon name="map" size={18} />
              See exactly what you understand, week by week
            </li>
          </ul>
        </div>
      </aside>

      <section className="login__panel">
        <div className="login-card">
          <div className="login-card__mobile-brand">
            <Brand tagline={false} />
          </div>

          <div className="stack gap-8">
            <h2 className="login-card__title">{isSignup ? 'Create your account' : 'Welcome back'}</h2>
            <p className="login-card__sub">
              {isSignup ? 'Your students are waiting to be taught.' : 'Your students have questions. Sign in to answer them.'}
            </p>
          </div>

          <button type="button" className="btn-sso" onClick={() => finish(DEMO_USER, 'canvas')} disabled={!!busy}>
            <span className="btn-sso__mark">
              <Icon name="cap" size={20} />
            </span>
            {busy === 'canvas' ? 'Connecting to Canvas…' : 'Continue with Canvas'}
          </button>
          <p className="fine-print">Uses your university's Canvas sign-in, so your subjects sync automatically.</p>

          <div className="divider-label">
            <span>or with your email</span>
          </div>

          <form className="stack gap-16" onSubmit={handleSubmit} noValidate>
            {isSignup && (
              <div className="field">
                <label htmlFor="name">Full name</label>
                <input id="name" className="input" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Riya Sharma" />
              </div>
            )}

            <div className="field">
              <label htmlFor="email">University email</label>
              <input
                id="email"
                type="email"
                className="input"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@uni.edu.au"
              />
            </div>

            <div className="field">
              <div className="field__row">
                <label htmlFor="password">Password</label>
                {!isSignup && (
                  <a href="#forgot" className="link-sm">
                    Forgot password?
                  </a>
                )}
              </div>
              <div className="input-wrap">
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  className="input"
                  autoComplete={isSignup ? 'new-password' : 'current-password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={isSignup ? 'At least 6 characters' : '••••••••'}
                />
                <button
                  type="button"
                  className="input-wrap__reveal"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  <Icon name={showPassword ? 'eyeOff' : 'eye'} size={20} />
                </button>
              </div>
            </div>

            <label className="checkbox">
              <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
              Keep me signed in on this device
            </label>

            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}

            <button type="submit" className="btn btn--violet btn--lg btn--block" disabled={!!busy}>
              {busy === 'email' ? 'Signing in…' : isSignup ? 'Create account' : 'Sign in'}
              {!busy && <Icon name="arrowRight" size={18} stroke={2} />}
            </button>
          </form>

          <p className="login-card__switch">
            {isSignup ? 'Already have an account?' : 'New to Pupil?'}{' '}
            <button type="button" className="link-btn" onClick={switchMode}>
              {isSignup ? 'Sign in' : 'Create an account'}
            </button>
          </p>
        </div>
      </section>
    </div>
  )
}
