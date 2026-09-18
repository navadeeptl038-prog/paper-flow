/**
 * PaperFlow AI — External Connectors API Service (Stages 18–19)
 *
 * Handles Google Drive and Gmail OAuth 2.0 connection lifecycle,
 * status verification, search, and account disconnection.
 *
 * Security:
 * - Google login != Google Drive / Gmail connector (each requires separate consent).
 * - Minimum required scopes: drive.readonly / gmail.readonly + userinfo.email.
 * - Client secrets and tokens are never stored or exposed frontend-side.
 */

import { api, ApiError } from './api'
import { supabase } from './auth'

/**
 * Retrieve the current Supabase session access token for authenticated API calls.
 * @returns {Promise<string|null>}
 */
async function getAuthToken() {
	if (!supabase) return null
	try {
		const { data } = await supabase.auth.getSession()
		return data?.session?.access_token || null
	} catch {
		return null
	}
}

// ---------------------------------------------------------------------------
// Combined Status
// ---------------------------------------------------------------------------

/**
 * List connection statuses for all external providers (Google Drive, Gmail, etc.)
 * @param {string|null} [explicitToken]
 * @returns {Promise<Array<{ provider: string, name: string, connected: boolean, account_email?: string, status: string, scopes: string[] }>>}
 */
export async function listConnectorsStatus(explicitToken = null) {
	const token = explicitToken || (await getAuthToken())
	return api.get('/api/connectors/status', { token })
}

// ---------------------------------------------------------------------------
// Google Drive
// ---------------------------------------------------------------------------

/**
 * Get current connection status for Google Drive.
 * @param {string|null} [explicitToken]
 */
export async function getGoogleDriveStatus(explicitToken = null) {
	const token = explicitToken || (await getAuthToken())
	return api.get('/api/connectors/google-drive/status', { token })
}

/**
 * Initiate Google Drive OAuth consent flow.
 * @param {string|null} [explicitToken]
 */
export async function getGoogleDriveAuthorizeUrl(explicitToken = null) {
	const token = explicitToken || (await getAuthToken())
	return api.get('/api/connectors/google-drive/authorize', { token })
}

/**
 * Search documents in user's connected Google Drive.
 * @param {string} query
 * @param {string|null} [explicitToken]
 */
export async function searchGoogleDrive(query, explicitToken = null) {
	if (!query || !query.trim()) {
		return { provider: 'google_drive', query: '', count: 0, files: [] }
	}
	const token = explicitToken || (await getAuthToken())
	const encodedQ = encodeURIComponent(query.trim())
	return api.get(`/api/connectors/google-drive/search?q=${encodedQ}`, { token })
}

/**
 * Disconnect Google Drive and revoke stored credentials.
 * @param {string|null} [explicitToken]
 */
export async function disconnectGoogleDrive(explicitToken = null) {
	const token = explicitToken || (await getAuthToken())
	return api.post('/api/connectors/google-drive/disconnect', {}, { token })
}

// ---------------------------------------------------------------------------
// Gmail
// ---------------------------------------------------------------------------

/**
 * Get current connection status for Gmail.
 * @param {string|null} [explicitToken]
 */
export async function getGmailStatus(explicitToken = null) {
	const token = explicitToken || (await getAuthToken())
	return api.get('/api/connectors/gmail/status', { token })
}

/**
 * Initiate Gmail OAuth consent flow (read-only — no send/delete/modify).
 * @param {string|null} [explicitToken]
 */
export async function getGmailAuthorizeUrl(explicitToken = null) {
	const token = explicitToken || (await getAuthToken())
	return api.get('/api/connectors/gmail/authorize', { token })
}

/**
 * Search messages in user's connected Gmail.
 * @param {string} query
 * @param {string|null} [explicitToken]
 */
export async function searchGmail(query, explicitToken = null) {
	if (!query || !query.trim()) {
		return { provider: 'gmail', query: '', count: 0, messages: [] }
	}
	const token = explicitToken || (await getAuthToken())
	const encodedQ = encodeURIComponent(query.trim())
	return api.get(`/api/connectors/gmail/search?q=${encodedQ}`, { token })
}

/**
 * Disconnect Gmail and revoke stored credentials.
 * @param {string|null} [explicitToken]
 */
export async function disconnectGmail(explicitToken = null) {
	const token = explicitToken || (await getAuthToken())
	return api.post('/api/connectors/gmail/disconnect', {}, { token })
}

// ---------------------------------------------------------------------------
// Unified connector service object for components
// ---------------------------------------------------------------------------

export const connectorService = {
	listStatus: listConnectorsStatus,

	getStatus: async (provider = 'google_drive', token = null) => {
		const prov = provider.toLowerCase().replace(/[\s-]/g, '_')
		if (prov === 'google_drive' || prov === 'drive') {
			return getGoogleDriveStatus(token)
		}
		if (prov === 'gmail') {
			return getGmailStatus(token)
		}
		const all = await listConnectorsStatus(token)
		return all.find((c) => c.provider === prov) || { provider: prov, connected: false, status: 'not_connected' }
	},

	connect: async (provider = 'google_drive', token = null) => {
		const prov = provider.toLowerCase().replace(/[\s-]/g, '_')
		if (prov === 'google_drive' || prov === 'drive') {
			return getGoogleDriveAuthorizeUrl(token)
		}
		if (prov === 'gmail') {
			return getGmailAuthorizeUrl(token)
		}
		return { provider: prov, connected: true }
	},

	disconnect: async (provider = 'google_drive', token = null) => {
		const prov = provider.toLowerCase().replace(/[\s-]/g, '_')
		if (prov === 'google_drive' || prov === 'drive') {
			return disconnectGoogleDrive(token)
		}
		if (prov === 'gmail') {
			return disconnectGmail(token)
		}
		return { provider: prov, disconnected: true, message: `Disconnected ${provider}` }
	},

	search: async (query, provider = 'google_drive', token = null) => {
		const prov = provider.toLowerCase().replace(/[\s-]/g, '_')
		if (prov === 'gmail') {
			return searchGmail(query, token)
		}
		return searchGoogleDrive(query, token)
	},
}

export default connectorService
