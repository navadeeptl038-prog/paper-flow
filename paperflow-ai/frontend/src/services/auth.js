/**
 * PaperFlow AI — Supabase Auth service (Stage 8 + Stage 9)
 *
 * Authentication architecture:
 *
 *   SIGNUP:
 *     signUp() → Supabase sends email with 6-digit OTP (type: 'signup')
 *     verifyOtp({ email, token, type: 'signup' }) → session established
 *
 *   PASSWORD LOGIN (two-step):
 *     1. signInWithPassword() → validates credentials (session A created by Supabase)
 *     2. signOut({ scope: 'local' }) → discard session A locally
 *     3. sendLoginOtp({ email }) → Supabase sends 6-digit OTP (type: 'email')
 *     4. verifyOtp({ email, token, type: 'email' }) → session B established
 *     Result: the ONLY session in Supabase storage comes from the OTP step
 *
 *   GOOGLE OAuth:
 *     loginWithGoogle() → Supabase redirect to Google → callback → session established
 *     No extra OTP step (Google handles its own 2FA)
 *
 * Security rules:
 *   - Only VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY are used here (public values)
 *   - service_role key, Gemini key, and backend secrets never appear here
 *   - OTP codes exist only in the user's email and in a controlled React input state
 *   - OTP codes are NEVER stored in localStorage, logged, or sent to our backend
 *   - Sessions are managed by Supabase's own storage — we never call localStorage manually
 */

import { createClient } from '@supabase/supabase-js'

// ---------------------------------------------------------------------------
// Supabase client
// ---------------------------------------------------------------------------

function readSupabaseConfig() {
	const url     = (import.meta.env.VITE_SUPABASE_URL      ?? '').trim()
	const anonKey = (import.meta.env.VITE_SUPABASE_ANON_KEY ?? '').trim()

	if (!url) {
		throw new Error(
			'VITE_SUPABASE_URL is not configured. ' +
			'Add it to frontend/.env — use the public project URL, not a secret.',
		)
	}
	if (!anonKey) {
		throw new Error(
			'VITE_SUPABASE_ANON_KEY is not configured. ' +
			'Add the anon/public key from Supabase → Project Settings → API.',
		)
	}

	return { url, anonKey }
}

/** @type {import('@supabase/supabase-js').SupabaseClient|null} */
let _supabase = null

export function getSupabaseClient() {
	if (_supabase) return _supabase
	const { url, anonKey } = readSupabaseConfig()
	_supabase = createClient(url, anonKey, {
		auth: {
			persistSession:     true,   // Supabase owns localStorage — we never touch it
			autoRefreshToken:   true,
			detectSessionInUrl: true,   // handles OAuth callback hash
		},
	})
	return _supabase
}

export const supabase = getSupabaseClient()

// ---------------------------------------------------------------------------
// AuthError class
// ---------------------------------------------------------------------------

/**
 * Normalised error from any auth operation.
 *
 * Properties:
 *   message    {string}        Human-readable, safe to display
 *   code       {string}        Machine-readable slug
 *   status     {number|null}   HTTP status from Supabase (if available)
 *   raw        {unknown}       Original error for debugging
 */
export class AuthError extends Error {
	constructor(message, { code = 'auth_error', status = null, raw = null } = {}) {
		super(message)
		this.name   = 'AuthError'
		this.code   = code
		this.status = status
		this.raw    = raw
	}
}

/** @param {unknown} error @param {string} [fallback] @returns {AuthError} */
function normalise(error, fallback = 'An authentication error occurred.') {
	if (error instanceof AuthError) return error
	const raw = error
	if (error && typeof error === 'object') {
		const e = /** @type {Record<string,unknown>} */ (error)
		const message = typeof e.message === 'string' && e.message.trim() ? e.message.trim() : fallback
		const status  = typeof e.status  === 'number' ? e.status  : null
		const code    = typeof e.code    === 'string' ? e.code    : 'auth_error'
		return new AuthError(message, { code, status, raw })
	}
	return new AuthError(fallback, { raw })
}

// ---------------------------------------------------------------------------
// Auth service
// ---------------------------------------------------------------------------

export const authService = {

	// ── Sign up ──────────────────────────────────────────────────────────────

	/**
	 * Create a new account.
	 * Supabase sends a 6-digit OTP to the email (or a magic-link if OTP is not
	 * enabled on the project — check Supabase → Auth → Email → OTP).
	 *
	 * @param {{ email: string, password: string, username?: string }} params
	 * @returns {Promise<{ user: import('@supabase/supabase-js').User|null, needsVerification: boolean }>}
	 */
	async signup({ email, password, username }) {
		const { data, error } = await supabase.auth.signUp({
			email,
			password,
			options: { data: username ? { username } : undefined },
		})
		if (error) throw normalise(error, 'Sign up failed. Please check your details and try again.')
		const needsVerification = data.user != null && data.session == null
		return { user: data.user, needsVerification }
	},

	// ── Password login (step 1 of 2) ─────────────────────────────────────────

	/**
	 * Step 1: Verify email + password credentials via Supabase.
	 * On success, discards the resulting session locally and triggers an email OTP.
	 * The caller must then navigate to the verify screen.
	 *
	 * This ensures the ONLY persisted session is the one created by OTP verification.
	 *
	 * @param {{ email: string, password: string }} params
	 * @returns {Promise<{ email: string }>} The email to pass to verifyOtp
	 */
	async login({ email, password }) {
		const { error } = await supabase.auth.signInWithPassword({ email, password })
		if (error) throw normalise(error, 'Sign in failed. Check your email and password.')

		// Discard the password-login session locally — OTP verification will create the real one.
		await supabase.auth.signOut({ scope: 'local' })

		// Send the 6-digit email OTP (Supabase type: 'email').
		// shouldCreateUser: false ensures this only works for existing accounts.
		await authService.sendLoginOtp({ email })

		return { email }
	},

	// ── Send login OTP (step 2 of 2 for password login) ─────────────────────

	/**
	 * Send a fresh 6-digit OTP to the given email address.
	 * Used both from login() and from the "Resend" button on the verify screen.
	 *
	 * @param {{ email: string }} params
	 * @returns {Promise<void>}
	 */
	async sendLoginOtp({ email }) {
		const { error } = await supabase.auth.signInWithOtp({
			email,
			options: {
				shouldCreateUser: false, // reject if account does not exist
			},
		})
		if (error) throw normalise(error, 'Could not send verification code. Please try again.')
	},

	// ── Verify OTP (used for both signup and login flows) ────────────────────

	/**
	 * Verify the 6-digit OTP entered by the user.
	 * On success, Supabase establishes a full session and fires the SIGNED_IN event.
	 * AuthContext picks this up via onAuthStateChange.
	 *
	 * @param {{ email: string, token: string, type?: 'email'|'signup' }} params
	 *   type: 'signup' for the signup verification flow
	 *         'email'  for the post-login verification flow (default)
	 * @returns {Promise<{ user: import('@supabase/supabase-js').User, token: string }>}
	 */
	async verifyOtp({ email, token, type = 'email' }) {
		const { data, error } = await supabase.auth.verifyOtp({
			email,
			token,
			type,
		})
		if (error) {
			// Surface specific OTP errors clearly so the UI can show the right message
			const msg = error.message?.toLowerCase() ?? ''
			if (msg.includes('expired') || msg.includes('invalid') || msg.includes('otp')) {
				throw normalise(error, 'The code is invalid or has expired. Request a new one and try again.')
			}
			throw normalise(error, 'Verification failed. Check the code and try again.')
		}
		if (!data.session) throw new AuthError('Verification succeeded but no session was returned.', { code: 'no_session' })
		return { user: data.user, token: data.session.access_token }
	},

	// ── Resend signup verification email ─────────────────────────────────────

	/**
	 * Resend the signup verification OTP.
	 * @param {{ email: string }} params
	 */
	async resendVerification({ email }) {
		const { error } = await supabase.auth.resend({ type: 'signup', email })
		if (error) throw normalise(error, 'Could not resend verification email. Please try again shortly.')
	},

	// ── Google OAuth ──────────────────────────────────────────────────────────

	/**
	 * Begin Google sign-in via Supabase OAuth redirect.
	 * Google OAuth must be enabled in Supabase → Auth → Providers → Google.
	 * This grants login access only — NOT Drive or Gmail connector access.
	 *
	 * @param {{ redirectTo?: string }} [options]
	 */
	async loginWithGoogle({ redirectTo } = {}) {
		const { error } = await supabase.auth.signInWithOAuth({
			provider: 'google',
			options: {
				redirectTo: redirectTo ?? window.location.origin,
				queryParams: { access_type: 'offline', prompt: 'select_account' },
			},
		})
		if (error) throw normalise(error, 'Google sign-in could not be started. Please try again.')
	},

	// ── Get current session ───────────────────────────────────────────────────

	/**
	 * Return the active session and access token, or null if not signed in.
	 * Use token for authenticated API calls: api.get('/api/...', { token })
	 *
	 * @returns {Promise<{ user: import('@supabase/supabase-js').User, token: string }|null>}
	 */
	async getSession() {
		const { data, error } = await supabase.auth.getSession()
		if (error) throw normalise(error, 'Could not retrieve the current session.')
		if (!data.session) return null
		return { user: data.session.user, token: data.session.access_token }
	},

	// ── Sign out ──────────────────────────────────────────────────────────────

	/**
	 * Sign out the current user globally. Supabase removes its own session storage.
	 */
	async logout() {
		const { error } = await supabase.auth.signOut()
		if (error) throw normalise(error, 'Sign out failed. Please refresh the page and try again.')
	},

	// ── Auth state change listener ────────────────────────────────────────────

	/**
	 * Subscribe to auth events (SIGNED_IN, SIGNED_OUT, TOKEN_REFRESHED, etc.)
	 * @param {(event: string, session: import('@supabase/supabase-js').Session|null) => void} callback
	 * @returns {{ unsubscribe: () => void }}
	 */
	onAuthStateChange(callback) {
		const { data } = supabase.auth.onAuthStateChange(callback)
		return { unsubscribe: data.subscription.unsubscribe }
	},
}
