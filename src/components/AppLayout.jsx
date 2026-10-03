import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import Brand from './Brand'
import Icon from './Icon'
import { useAuth } from '../auth'

const NAV = [
  { to: '/', label: 'Home', icon: 'home', end: true },
  { to: '/setup', label: 'Subjects', icon: 'book' },
  { to: '/map', label: 'Understanding maps', icon: 'map' },
  { to: '/session', label: 'Past sessions', icon: 'clock' },
]

export default function AppLayout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="shell">
      <nav className="sidebar" aria-label="Main">
        <Brand />
        <div className="nav">
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end}>
              <Icon name={item.icon} />
              {item.label}
            </NavLink>
          ))}
        </div>
        <div className="sidebar__footer">
          <div className="sync-card">
            <div className="sync-card__title">
              <span className="status-dot" />
              Canvas connected
            </div>
            <div className="sync-card__sub">Synced 2 min ago · 3 subjects · Weeks 1–6</div>
          </div>
          <div className="user-row">
            <span className="avatar-initial avatar-initial--sm" aria-hidden="true">
              {user?.name?.[0] ?? '?'}
            </span>
            <span className="user-row__name">{user?.name}</span>
            <button type="button" className="icon-btn icon-btn--dark" onClick={handleLogout} aria-label="Log out" title="Log out">
              <Icon name="logout" size={18} />
            </button>
          </div>
        </div>
      </nav>
      <main className="main">
        <Outlet />
      </main>
    </div>
  )
}
