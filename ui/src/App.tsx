import { Route, Routes } from 'react-router-dom'
import { ProtectedRoute } from './components/ProtectedRoute'
import { BotDetail } from './pages/BotDetail'
import { Dashboard } from './pages/Dashboard'
import { Landing } from './pages/Landing'
import { Login } from './pages/Login'
import { NewBot } from './pages/NewBot'

/**
 * Top-level route table.
 *
 * `/` is the public landing page and `/dashboard` is the console, rather than
 * the console living at `/`. A signed-out visitor hitting the root should see
 * what the product is, not a redirect to a login form.
 */
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route element={<ProtectedRoute />}>
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/bots/new" element={<NewBot />} />
        <Route path="/bots/:id" element={<BotDetail />} />
      </Route>
    </Routes>
  )
}
