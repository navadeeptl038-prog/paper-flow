import { useState } from 'react'
import { ArrowRight, Eye, EyeOff, Sparkles } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { authService, AuthError } from '../services/auth'

// Simple email format check — full validation happens on the Supabase side
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export default function Login({ onNavigate }) {
	const { startPendingVerification } = useAuth()

	const [email,    setEmail]    = useState('')
	const [password, setPassword] = useState('')
	const [show,     setShow]     = useState(false)
	const [loading,  setLoading]  = useState(false)
	const [error,    setError]    = useState('')

	// ── Validation ────────────────────────────────────────────────────────────

	function validate() {
		if (!email.trim())           return 'Enter your email address.'
		if (!EMAIL_RE.test(email))   return 'Enter a valid email address.'
		if (!password)               return 'Enter your password.'
		if (password.length < 6)     return 'Password must be at least 6 characters.'
		return null
	}

	// ── Password login (two-step: credentials → OTP) ─────────────────────────

	async function handleSubmit(event) {
		event.preventDefault()
		setError('')

		const validationError = validate()
		if (validationError) return setError(validationError)

		setLoading(true)
		try {
			// authService.login():
			//   1. Verifies credentials via signInWithPassword
			//   2. Signs out the resulting session locally
			//   3. Sends a 6-digit OTP email via signInWithOtp
			// The ONLY persisted session comes from verifyOtp on the next screen.
			await authService.login({ email: email.trim(), password })

			// Store email in AuthContext (React state only — NOT localStorage)
			startPendingVerification(email.trim(), 'login')

			// Navigate to the verify screen
			onNavigate('verify')
		} catch (err) {
			if (err instanceof AuthError) {
				// Map common Supabase error codes to user-friendly messages
				if (err.status === 400 || err.code === 'invalid_credentials') {
					setError('Incorrect email or password. Please try again.')
				} else if (err.status === 429) {
					setError('Too many attempts. Please wait a moment and try again.')
				} else if (err.code === 'email_not_confirmed') {
					// Account exists but email not verified — send them to verify
					startPendingVerification(email.trim(), 'signup')
					onNavigate('verify')
					return
				} else {
					setError(err.message || 'Sign in failed. Please try again.')
				}
			} else {
				setError('Unable to reach the server. Check your connection and try again.')
			}
		} finally {
			setLoading(false)
		}
	}

	// ── Google OAuth ──────────────────────────────────────────────────────────

	async function handleGoogle() {
		setError('')
		try {
			const redirectTo = window.location.origin && window.location.origin !== 'about:blank'
				? window.location.origin
				: 'http://localhost:5173'
			await authService.loginWithGoogle({ redirectTo })
		} catch (err) {
			setError(err instanceof AuthError ? err.message : 'Google sign-in failed. Please try again.')
		}
	}

	// ── Render ────────────────────────────────────────────────────────────────

	return (
		<div className="auth-layout">
			<div className="auth-aside">
				<button className="brand auth-brand" onClick={() => onNavigate('login')}>
					<span className="brand-mark"><Sparkles size={16} /></span> paperflow
				</button>
				<div>
					<p className="auth-quote">"The fastest way to find what matters is to stop looking in just one place."</p>
					<span className="auth-quote-by">PaperFlow AI</span>
				</div>
				<span className="auth-aside-footer">Your documents. Your context. Your answers.</span>
			</div>

			<main className="auth-card">
				<div className="auth-card-inner">
					<span className="mobile-auth-logo"><Sparkles size={15} /> paperflow</span>
					<span className="eyebrow">Welcome back</span>
					<h1>Find your flow.</h1>
					<p className="auth-subtitle">Sign in to your personal document intelligence.</p>

					<form onSubmit={handleSubmit} className="auth-form" noValidate>
						<label>
							Email
							<input
								id="login-email"
								type="email"
								value={email}
								onChange={(e) => { setEmail(e.target.value); setError('') }}
								placeholder="you@example.com"
								autoComplete="email"
								disabled={loading}
							/>
						</label>

						<label>
							Password
							<span className="password-field">
								<input
									id="login-password"
									type={show ? 'text' : 'password'}
									value={password}
									onChange={(e) => { setPassword(e.target.value); setError('') }}
									placeholder="Enter your password"
									autoComplete="current-password"
									disabled={loading}
								/>
								<button
									type="button"
									onClick={() => setShow(!show)}
									aria-label={show ? 'Hide password' : 'Show password'}
									tabIndex={-1}
								>
									{show ? <EyeOff size={17} /> : <Eye size={17} />}
								</button>
							</span>
						</label>

						{error && <p className="form-error" role="alert">{error}</p>}

						<button
							id="login-submit"
							className="button primary wide"
							type="submit"
							disabled={loading}
						>
							{loading
								? <><span className="spinner" /> Signing in…</>
								: <><span>Sign in</span> <ArrowRight size={17} /></>
							}
						</button>
					</form>

					<div className="auth-divider"><span>or</span></div>

					<button
						id="login-google"
						className="google-button"
						onClick={handleGoogle}
						disabled={loading}
						type="button"
					>
						Continue with Google <span aria-hidden>G</span>
					</button>

					<p className="auth-switch">
						New to PaperFlow?{' '}
						<button onClick={() => onNavigate('signup')}>Create an account</button>
					</p>
				</div>
			</main>
		</div>
	)
}
