/**
 * AuthContext — Supabase-backed authentication state for PaperFlow AI.
 *
 * State managed here:
 *   user              Supabase User object | null  — set only after full OTP verification
 *   session           Supabase Session | null       — the active session
 *   loading           boolean                       — true during initial session check
 *   pendingEmail      string | null                 — email waiting for OTP (in-memory only)
 *   pendingMode       'login'|'signup'|null         — which OTP flow is pending
 *
 * Security:
 *   - user is only set after onAuthStateChange fires SIGNED_IN (which happens after OTP)
 *   - pendingEmail is stored in React state only — never localStorage, never a cookie
 *   - No OTP codes are ever stored anywhere in this context
 *   - Supabase manages its own session storage — we never call localStorage for tokens
 */

import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { authService } from '../services/auth'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
	/** @type {[import('@supabase/supabase-js').User|null, Function]} */
	const [user, setUser] = useState(null)

	/** @type {[import('@supabase/supabase-js').Session|null, Function]} */
	const [session, setSession] = useState(null)

	// True while we are checking the initial session — prevents flash of login screen
	const [loading, setLoading] = useState(true)

	// In-memory pending verification state.
	// These are NEVER written to localStorage — a page refresh intentionally clears them.
	const [pendingEmail, setPendingEmail] = useState(null)
	const [pendingMode,  setPendingMode]  = useState(null)   // 'login' | 'signup'

	// ── Initial session check ─────────────────────────────────────────────────

	useEffect(() => {
		let cancelled = false

		authService.getSession()
			.then((result) => {
				if (cancelled) return
				if (result) {
					setUser(result.user)
					setSession(/** @type {any} */ ({ access_token: result.token }))
				}
			})
			.catch(() => {
				// No session or Supabase not configured — stay logged out
			})
			.finally(() => {
				if (!cancelled) setLoading(false)
			})

		return () => { cancelled = true }
	}, [])

	// ── Auth state change subscription ───────────────────────────────────────

	useEffect(() => {
		const { unsubscribe } = authService.onAuthStateChange((event, activeSession) => {
			if (event === 'SIGNED_IN') {
				setUser(activeSession?.user ?? null)
				setSession(activeSession)
				// Clear pending verification state — the user is now fully signed in
				setPendingEmail(null)
				setPendingMode(null)
				setLoading(false)
			} else if (event === 'SIGNED_OUT') {
				setUser(null)
				setSession(null)
				setLoading(false)
			} else if (event === 'TOKEN_REFRESHED') {
				setSession(activeSession)
			} else if (event === 'USER_UPDATED') {
				setUser(activeSession?.user ?? null)
			}
		})

		return unsubscribe
	}, [])

	// ── Helpers exposed to the app ────────────────────────────────────────────

	/**
	 * Get the current access token for authenticated API calls.
	 * Returns null when not signed in.
	 * @returns {string|null}
	 */
	const getToken = useCallback(() => {
		return session?.access_token ?? null
	}, [session])

	/**
	 * Store the email waiting for OTP verification.
	 * Called by Login/Signup pages before navigating to the verify screen.
	 * @param {string} email
	 * @param {'login'|'signup'} mode
	 */
	const startPendingVerification = useCallback((email, mode) => {
		setPendingEmail(email)
		setPendingMode(mode)
	}, [])

	/**
	 * Expose a logout function compatible with components that call it directly.
	 */
	const logout = useCallback(async () => {
		try {
			await authService.logout()
		} catch {
			// Even if logout API fails, clear local state
			setUser(null)
			setSession(null)
		}
	}, [])

	return (
		<AuthContext.Provider value={{
			user,
			session,
			loading,
			pendingEmail,
			pendingMode,
			getToken,
			startPendingVerification,
			logout,
		}}>
			{children}
		</AuthContext.Provider>
	)
}

export function useAuth() {
	const context = useContext(AuthContext)
	if (!context) throw new Error('useAuth must be used inside <AuthProvider>')
	return context
}
