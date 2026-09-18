import { useState, useEffect } from 'react'
import { ArrowLeft, CheckCircle2, RefreshCw, Sparkles, AlertCircle } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { authService, AuthError } from '../services/auth'

export default function VerifyEmail({ onNavigate }) {
	const { pendingEmail, pendingMode } = useAuth()

	// In-memory pending email or fallback manual entry if user refreshed
	const [email, setEmail] = useState(pendingEmail || '')
	const [code, setCode] = useState('')
	const [loading, setLoading] = useState(false)
	const [resending, setResending] = useState(false)
	const [verified, setVerified] = useState(false)
	const [error, setError] = useState('')
	const [infoMessage, setInfoMessage] = useState('')
	const [cooldown, setCooldown] = useState(60)

	// Sync with pendingEmail if it changes in context
	useEffect(() => {
		if (pendingEmail) {
			setEmail(pendingEmail)
		}
	}, [pendingEmail])

	// Cooldown timer for the Resend button
	useEffect(() => {
		if (cooldown <= 0) return
		const timer = setInterval(() => {
			setCooldown((prev) => (prev > 0 ? prev - 1 : 0))
		}, 1000)
		return () => clearInterval(timer)
	}, [cooldown])

	// Handle OTP submission
	async function handleSubmit(event) {
		event.preventDefault()
		setError('')
		setInfoMessage('')

		const trimmedCode = code.trim()
		const targetEmail = email.trim()

		if (!targetEmail) {
			setError('No registered email found. Please return to sign in.')
			return
		}

		if (trimmedCode.length !== 6) {
			setError('Please enter the 6-digit verification code.')
			return
		}

		setLoading(true)
		try {
			// Choose verification type: 'signup' for signup confirmations, 'email' for post-login OTP
			const otpType = pendingMode === 'signup' ? 'signup' : 'email'
			await authService.verifyOtp({
				email: targetEmail,
				token: trimmedCode,
				type: otpType,
			})

			// Successful verification
			setVerified(true)
			// Navigation to home or login will be handled by AuthContext state change or click
			setTimeout(() => {
				onNavigate('home')
			}, 1200)
		} catch (err) {
			if (!navigator.onLine) {
				setError('Network failure: You appear to be offline. Check your internet connection.')
				return
			}

			if (err instanceof AuthError) {
				const msg = (err.message || '').toLowerCase()
				if (msg.includes('expired')) {
					setError('Verification code has expired. Please click "Resend code" for a new one.')
				} else if (msg.includes('invalid') || msg.includes('incorrect') || msg.includes('otp')) {
					setError('Incorrect verification code. Please check your email and try again.')
				} else if (err.status === 429) {
					setError('Too many attempts. Please wait before trying again.')
				} else {
					setError(err.message || 'Verification failed. Please try again.')
				}
			} else if (err.name === 'TypeError' && err.message?.includes('fetch')) {
				setError('Network failure: Unable to reach verification server. Please try again.')
			} else {
				setError('Incorrect or expired verification code. Please request a new code.')
			}
		} finally {
			setLoading(false)
		}
	}

	// Handle resending verification code
	async function handleResend() {
		if (cooldown > 0 || resending) return
		setError('')
		setInfoMessage('')

		const targetEmail = email.trim()
		if (!targetEmail) {
			setError('Please return to sign in to request a verification code.')
			return
		}

		setResending(true)
		try {
			if (pendingMode === 'signup') {
				await authService.resendVerification({ email: targetEmail })
			} else {
				await authService.sendLoginOtp({ email: targetEmail })
			}
			setInfoMessage(`A fresh verification code was sent to ${targetEmail}`)
			setCooldown(60)
		} catch (err) {
			if (!navigator.onLine) {
				setError('Network failure: Could not reach the server to resend code.')
			} else if (err instanceof AuthError) {
				if (err.status === 429) {
					setError('Rate limit exceeded. Please wait a moment before resending.')
				} else {
					setError(err.message || 'Could not resend verification code. Try again shortly.')
				}
			} else {
				setError('Network failure. Please try again.')
			}
		} finally {
			setResending(false)
		}
	}

	const formatCooldown = (seconds) => {
		const mins = Math.floor(seconds / 60)
		const secs = seconds % 60
		return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
	}

	return (
		<div className="verify-layout">
			<button className="brand auth-brand" onClick={() => onNavigate('login')}>
				<span className="brand-mark"><Sparkles size={16} /></span> paperflow
			</button>

			<main className="verify-card">
				{verified ? (
					<>
						<CheckCircle2 className="success-icon" size={48} />
						<span className="eyebrow">All set</span>
						<h1>Email verified.</h1>
						<p>Your PaperFlow workspace is ready. Taking you to your dashboard…</p>
						<button
							id="continue-home-btn"
							className="button primary wide"
							onClick={() => onNavigate('home')}
						>
							Continue to workspace
						</button>
					</>
				) : (
					<>
						<button
							className="back-link"
							onClick={() => onNavigate(pendingMode === 'signup' ? 'signup' : 'login')}
						>
							<ArrowLeft size={16} /> Back to {pendingMode === 'signup' ? 'sign up' : 'sign in'}
						</button>

						<span className="eyebrow">One last step</span>
						<h1>Verify it's you</h1>

						<p>
							{email ? (
								<>A verification code was sent to <strong>{email}</strong>. Enter it below to complete authentication.</>
							) : (
								<>Enter the 6-digit verification code sent to your registered email address.</>
							)}
						</p>

						{!pendingEmail && (
							<div style={{ marginBottom: '16px' }}>
								<label style={{ fontSize: '11px', color: '#5e665f', fontWeight: 700 }}>
									Registered Email
									<input
										id="verify-email-input"
										type="email"
										value={email}
										onChange={(e) => { setEmail(e.target.value); setError('') }}
										placeholder="you@example.com"
										style={{
											width: '100%',
											padding: '10px',
											borderRadius: '7px',
											border: '1px solid #dcd9d0',
											marginTop: '4px',
											fontSize: '13px'
										}}
									/>
								</label>
							</div>
						)}

						<form onSubmit={handleSubmit} className="verify-form" noValidate>
							<label htmlFor="verify-code">
								Verification code
								<input
									id="verify-code"
									value={code}
									onChange={(event) => {
										setCode(event.target.value.replace(/\D/g, '').slice(0, 6))
										setError('')
									}}
									inputMode="numeric"
									placeholder="000000"
									maxLength={6}
									autoFocus
									disabled={loading}
								/>
							</label>

							{error && (
								<p className="form-error" role="alert" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
									<AlertCircle size={14} /> {error}
								</p>
							)}

							{infoMessage && (
								<p style={{ color: '#2e7d32', fontSize: '12px', margin: '-4px 0 2px' }} role="status">
									{infoMessage}
								</p>
							)}

							<button
								id="verify-submit"
								className="button primary wide"
								disabled={loading || code.trim().length !== 6}
								type="submit"
							>
								{loading ? <span className="spinner" /> : 'Verify'}
							</button>
						</form>

						<button
							id="verify-resend"
							className="resend-button"
							onClick={handleResend}
							disabled={resending || cooldown > 0}
							type="button"
						>
							<RefreshCw size={15} className={resending ? 'spinner' : ''} />
							{cooldown > 0 ? (
								<>Resend code <span>in {formatCooldown(cooldown)}</span></>
							) : (
								'Resend code'
							)}
						</button>
					</>
				)}
			</main>
		</div>
	)
}
