import { useState } from 'react'
import { Check, ExternalLink, HardDrive, Mail, Unplug, Loader2, AlertCircle } from 'lucide-react'
import { connectorService } from '../services/connectorApi'

const icons = {
	'Google Drive': HardDrive,
	'google_drive': HardDrive,
	'Gmail': Mail,
	'gmail': Mail,
	'Local Storage': HardDrive,
	'local_storage': HardDrive,
}

export default function ConnectorCard({ connector, onToggle }) {
	const [isLoading, setIsLoading] = useState(false)
	const [error, setError] = useState(null)

	const isDrive = connector.name === 'Google Drive' || connector.provider === 'google_drive'
	const Icon = icons[connector.name] || icons[connector.provider] || HardDrive

	const isConnected = Boolean(connector.connected)
	const isRevoked = connector.status === 'revoked'
	const isExpired = connector.status === 'expired'

	const accountLabel = connector.account || connector.account_email || (isConnected ? 'Connected' : null)

	const handleAction = async () => {
		setError(null)

		// Non-Drive connectors or custom onToggle handlers
		if (!isDrive) {
			onToggle?.(connector.name)
			return
		}

		// Google Drive connection lifecycle
		if (isConnected) {
			// Disconnect flow
			try {
				setIsLoading(true)
				await connectorService.disconnect('google_drive')
				if (onToggle) {
					onToggle(connector.name)
				}
			} catch (err) {
				console.warn('Failed to disconnect Google Drive:', err)
				// Fallback to local toggle if API not ready
				onToggle?.(connector.name)
			} finally {
				setIsLoading(false)
			}
		} else {
			// Connect flow — initiate OAuth consent
			try {
				setIsLoading(true)
				const res = await connectorService.connect('google_drive')
				if (res?.authorization_url) {
					window.location.href = res.authorization_url
					return
				}
				// If no redirect URL provided, fall back to UI toggle
				onToggle?.(connector.name)
			} catch (err) {
				const msg = err?.message || err?.details?.detail || 'Google OAuth is not configured on the backend.'
				setError(msg)
				// Graceful fallback for UI preview
				if (onToggle) {
					onToggle(connector.name)
				}
			} finally {
				setIsLoading(false)
			}
		}
	}

	let statusBadgeClass = 'connector-state'
	let statusText = 'Not connected'

	if (isConnected) {
		statusBadgeClass += ' connected'
		statusText = 'Connected'
	} else if (isRevoked) {
		statusBadgeClass += ' revoked'
		statusText = 'Access revoked'
	} else if (isExpired) {
		statusBadgeClass += ' expired'
		statusText = 'Token expired'
	}

	return (
		<article className="connector-card">
			<div className={`connector-logo ${connector.name === 'Gmail' || connector.provider === 'gmail' ? 'gmail' : ''}`}>
				<Icon size={22} />
			</div>

			<div className="connector-info">
				<div>
					<strong>{connector.name || 'Connector'}</strong>
					<span className={statusBadgeClass}>
						<span />
						{statusText}
					</span>
				</div>

				<p>{connector.description}</p>

				{accountLabel && (
					<small style={{ display: 'block', marginTop: '2px' }}>
						{accountLabel}
					</small>
				)}

				{error && (
					<div style={{ display: 'flex', alignItems: 'center', gap: '4px', color: '#b54e42', fontSize: '10px', marginTop: '4px' }}>
						<AlertCircle size={12} />
						<span>{error}</span>
					</div>
				)}
			</div>

			<button
				type="button"
				className={`connector-action ${isConnected ? 'connected-action' : ''}`}
				onClick={handleAction}
				disabled={isLoading}
				title={isConnected ? 'Click to disconnect' : 'Click to connect'}
			>
				{isLoading ? (
					<>
						<Loader2 size={15} className="animate-spin" />
						<span>{isConnected ? 'Disconnecting...' : 'Connecting...'}</span>
					</>
				) : isConnected ? (
					<>
						<Check size={15} />
						<span>Connected</span>
					</>
				) : (
					<>
						<ExternalLink size={15} />
						<span>{isRevoked || isExpired ? 'Reconnect' : 'Connect'}</span>
					</>
				)}
			</button>
		</article>
	)
}
