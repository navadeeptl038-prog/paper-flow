/**
 * useAuth — hook for accessing authentication state and actions.
 *
 * Re-exports the AuthContext hook as a clean named default export.
 * Import this hook in any component that needs auth state or actions:
 *
 *   import useAuth from '../hooks/useAuth'
 *
 *   function MyComponent() {
 *     const { user, loading, logout, getToken } = useAuth()
 *     ...
 *   }
 *
 * Available values:
 *   user                  Supabase User | null       — null until OTP verified
 *   session               Supabase Session | null
 *   loading               boolean                    — true during initial session check
 *   pendingEmail          string | null              — email awaiting OTP (in-memory)
 *   pendingMode           'login'|'signup'|null
 *   getToken()            → string|null              — current access token for API calls
 *   startPendingVerification(email, mode) → void
 *   logout()              → Promise<void>
 */

import { useAuth as useAuthContext } from '../context/AuthContext'

export default function useAuth() {
	return useAuthContext()
}
