/*
 * MOCK AUTHENTICATION
 * -------------------
 * This keeps a fake "logged in" user in localStorage so the prototype feels real.
 * There is no server and no password check.
 *
 * To make it real later, replace login() with a call to your backend, e.g.
 *   - Canvas OAuth2 (Canvas developer key) for "Continue with Canvas"
 *   - or Firebase Auth / Supabase Auth / Clerk for email + password
 */
import { createContext, useContext, useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

const STORAGE_KEY = 'pupil.user'

function loadUser() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function saveUser(user) {
  try {
    if (user) localStorage.setItem(STORAGE_KEY, JSON.stringify(user))
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* storage unavailable (private window etc.): stay logged in for this tab only */
  }
}

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(loadUser)

  const login = (nextUser, { remember = true } = {}) => {
    setUser(nextUser)
    if (remember) saveUser(nextUser)
  }

  const logout = () => {
    setUser(null)
    saveUser(null)
  }

  return <AuthContext.Provider value={{ user, login, logout }}>{children}</AuthContext.Provider>
}

export function useAuth() {
  return useContext(AuthContext)
}

/** Wrap any route that needs a signed-in user. */
export function RequireAuth({ children }) {
  const { user } = useAuth()
  const location = useLocation()
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return children
}
