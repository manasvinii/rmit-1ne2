import { Navigate, Route, Routes } from 'react-router-dom'
import { RequireAuth } from './auth'
import AppLayout from './components/AppLayout'
import Login from './pages/Login'
import Home from './pages/Home'
import Setup from './pages/Setup'
import Session from './pages/Session'
import UnderstandingMap from './pages/UnderstandingMap'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />

      {/* Pages that share the dark sidebar */}
      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route index element={<Home />} />
        <Route path="setup" element={<Setup />} />
        <Route path="map" element={<UnderstandingMap />} />
      </Route>

      {/* The teaching session is full-screen, without the sidebar */}
      <Route
        path="/session"
        element={
          <RequireAuth>
            <Session />
          </RequireAuth>
        }
      />

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
