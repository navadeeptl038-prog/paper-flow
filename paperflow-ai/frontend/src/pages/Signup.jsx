import { useState } from 'react'
import { ArrowRight, Eye, EyeOff, Sparkles } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { authService, AuthError } from '../services/auth'

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

// Password requirements — shown inline to the user
const PASSWORD_MIN = 8
const HAS_UPPERCASE = /[A-Z]/
const HAS_DIGIT     = /[0-9]/

function validatePassword(pw) {
	if (pw.length < PASSWORD_MIN)    return `Password must be at least ${PASSWORD_MIN} characters.`
	if (!HAS_UPPERCASE.test(pw))     return 'Password must contain at least one uppercase letter.'
	if (!HAS_DIGIT.test(pw))         return 'Password must contain at least one number.'
	return null
}

export default function Signup({ onNavigate }) {
	const { startPendingVerification } = useAuth()

	const [form, setForm] = useState({ username: '', email: '', password: '', confirm: '' })
	const [show,    setShow]    = useState(false)
	const [loading, setLoading] = useState(false)
	const [error,   setError]   = useState('')

	const update = (key) => (e) => { setForm({ ...form, [key]: e.target.value }); setError('') }

	// ── Validation ────────────────────────────────────────────────────────────

	function validate() {
		if (!form.username.trim())              return 'Enter a username.'
		if (form.username.trim().length < 2)    return 'Username must be at least 2 characters.'
		if (!form.email.trim())                 return 'Enter your email address.'
		if (!EMAIL_RE.test(form.email))         return 'Enter a valid email address.'
		const pwError = validatePassword(form.password)
		if (pwError)                            return pwError
		if (form.password !== form.confirm)     return 'Passwords do not match.'
		return null
	}

	// ── Signup ────────────────────────────────────────────────────────────────

	async function handleSubmit(event) {
		event.preventDefault()
		setError('')

		const validationError = validate()
		if (validationError) return setError(validationError)

		setLoading(true)
		try {
			const { needsVerification } = await authService.signup({
				email:    form.email.trim(),
				password: form.password,
				username: form.username.trim(),
			})

			// Store email in AuthContext React state for the verify screen
			startPendingVerification(form.email.trim(), 'signup')

			if (needsVerification) {
				// Standard path: Supabase sent a confirmation OTP or magic link
				onNavigate('verify')
			} else {
				// Email confirmation disabled — user is immediately signed in
				onNavigate('home')
			}
		} catch (err) {
			if (err instanceof AuthError) {
				if (err.status === 422 || err.message?.toLowerCase().includes('already registered')) {
					setError('An account with this email already exists. Try signing in instead.')
				} else if (err.status === 429) {
					setError('Too many sign-up attempts. Please wait a moment and try again.')
				} else {
					setError(err.message || 'Account creation failed. Please try again.')
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
			await authService.loginWithGoogle()
		} catch (err) {
			setError(err instanceof AuthError ? err.message : 'Google sign-in failed. Please try again.')
		}
	}

	// ── Password strength indicator ───────────────────────────────────────────

	function strengthLabel() {
		const pw = form.password
		if (!pw) return null
		if (pw.length < PASSWORD_MIN)              return { label: 'Too short', cls: 'strength-weak' }
		if (!HAS_UPPERCASE.test(pw) || !HAS_DIGIT.test(pw))
		                                           return { label: 'Weak',     cls: 'strength-weak' }
		if (pw.length < 12)                        return { label: 'Fair',     cls: 'strength-fair' }
		return                                            { label: 'Strong',   cls: 'strength-strong' }
	}

	const strength = strengthLabel()

	// ── Render ────────────────────────────────────────────────────────────────

	return (
		<div className="auth-layout">
			<div className="auth-aside signup-aside">
				<button className="brand auth-brand" onClick={() => onNavigate('login')}>
					<span className="brand-mark"><Sparkles size={16} /></span> paperflow
				</button>
				<div>
					<span className="eyebrow">A calmer way to search</span>
					<h2>Bring every source into focus.</h2>
					<p>One private place for the files, messages, and answers you need every day.</p>
				</div>
				<span className="auth-aside-footer">No clutter. Just clarity.</span>
			</div>

			<main className="auth-card">
				<div className="auth-card-inner">
					<span className="mobile-auth-logo"><Sparkles size={15} /> paperflow</span>
					<span className="eyebrow">Start finding</span>
					<h1>Create your space.</h1>
					<p className="auth-subtitle">A smarter home for everything you need to remember.</p>

					<form onSubmit={handleSubmit} className="auth-form" noValidate>
						<label>
							Username
							<input
								id="signup-username"
								value={form.username}
								onChange={update('username')}
								placeholder="How should we call you?"
								autoComplete="username"
								disabled={loading}
							/>
						</label>

						<label>
							Email
							<input
								id="signup-email"
								type="email"
								value={form.email}
								onChange={update('email')}
								placeholder="you@example.com"
								autoComplete="email"
								disabled={loading}
							/>
						</label>

						<label>
							Password
							<span className="password-field">
								<input
									id="signup-password"
									type={show ? 'text' : 'password'}
									value={form.password}
									onChange={update('password')}
									placeholder="Create a password"
									autoComplete="new-password"
									disabled={loading}
								/>
								<button
									type="button"
									onClick={() => setShow(!show)}
									aria-label="Toggle password visibility"
									tabIndex={-1}
								>
									{show ? <EyeOff size={17} /> : <Eye size={17} />}
								</button>
							</span>
							{strength && (
								<span className={`password-strength ${strength.cls}`}>
									{strength.label}
								</span>
							)}
						</label>

						<label>
							Confirm password
							<input
								id="signup-confirm"
								type="password"
								value={form.confirm}
								onChange={update('confirm')}
								placeholder="Repeat your password"
								autoComplete="new-password"
								disabled={loading}
							/>
						</label>

						{error && <p className="form-error" role="alert">{error}</p>}

						<button
							id="signup-submit"
							className="button primary wide"
							type="submit"
							disabled={loading}
						>
							{loading
								? <><span className="spinner" /> Creating account…</>
								: <><span>Create account</span> <ArrowRight size={17} /></>
							}
						</button>
					</form>

					<div className="auth-divider"><span>or</span></div>

					<button
						id="signup-google"
						className="google-button"
						onClick={handleGoogle}
						disabled={loading}
						type="button"
					>
						Continue with Google <span aria-hidden>G</span>
					</button>

					<p className="auth-switch">
						Already have an account?{' '}
						<button onClick={() => onNavigate('login')}>Sign in</button>
					</p>
				</div>
			</main>
		</div>
	)
}
