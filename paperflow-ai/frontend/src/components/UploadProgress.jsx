import React from 'react'
import { AlertCircle, CheckCircle2, Loader2 } from 'lucide-react'

/**
 * UploadProgress component — displays file upload percentage and processing status.
 *
 * Requirements:
 * - Shows filename or summary
 * - Visual progress bar (0-100%)
 * - Shows processing status: 'uploading' -> 'uploaded' / 'pending'
 * - Displays error state if an error occurred
 * - Respects PaperFlow AI design tokens
 */
export default function UploadProgress({
	name = 'document.pdf',
	progress = 0,
	status = 'uploading', // 'idle' | 'uploading' | 'uploaded' | 'pending' | 'error'
	error = null,
	onDismiss = null,
}) {
	const clampedProgress = Math.max(0, Math.min(100, Math.round(progress)))
	const isError = Boolean(error) || status === 'error'
	const isComplete = (status === 'uploaded' || status === 'pending') && clampedProgress >= 100

	return (
		<div
			className={`upload-progress ${isError ? 'upload-progress-error' : ''}`}
			role="status"
			aria-live="polite"
		>
			<div className="upload-progress-head">
				<span title={name} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '75%' }}>
					{name}
				</span>
				<strong>
					{isError ? (
						<span style={{ color: '#b54e42' }}>Failed</span>
					) : (
						`${clampedProgress}%`
					)}
				</strong>
			</div>

			<div className="progress-track">
				<span
					style={{
						width: `${clampedProgress}%`,
						background: isError ? '#b54e42' : 'var(--coral, #e06c55)',
						transition: 'width 0.2s ease-in-out',
					}}
				/>
			</div>

			<div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '6px', marginTop: '4px' }}>
				<small style={{ display: 'flex', alignItems: 'center', gap: '4px', color: isError ? '#b54e42' : '#9c9f97' }}>
					{isError ? (
						<>
							<AlertCircle size={12} />
							<span>{error || 'Upload failed. Please check file type and size.'}</span>
						</>
					) : isComplete ? (
						<>
							<CheckCircle2 size={12} color="#62a064" />
							<span>Uploaded to secure storage (Status: pending processing)</span>
						</>
					) : (
						<>
							<Loader2 size={12} className="spin" style={{ animation: 'spin 1s linear infinite' }} />
							<span>Uploading to secure storage... ({clampedProgress}%)</span>
						</>
					)}
				</small>

				{onDismiss && (
					<button
						type="button"
						onClick={onDismiss}
						style={{
							background: 'transparent',
							border: 0,
							fontSize: '11px',
							color: '#8c928b',
							cursor: 'pointer',
							textDecoration: 'underline',
							padding: 0,
						}}
					>
						Dismiss
					</button>
				)}
			</div>
		</div>
	)
}
