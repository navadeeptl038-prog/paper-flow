/**
 * Shared frontend API client for PaperFlow AI.
 *
 * Base URL comes only from VITE_API_URL (see frontend/.env.example).
 * No localhost fallback in code — configure env explicitly for each environment.
 * Never put service-role keys, Gemini keys, or OAuth secrets here.
 */

export class ApiError extends Error {
	constructor(message, { status = null, code = 'api_error', details = null } = {}) {
		super(message)
		this.name = 'ApiError'
		this.status = status
		this.code = code
		this.details = details
	}
}

/** Local development default documented for humans — not used as a silent fallback. */
export const LOCAL_API_URL_HINT = 'http://127.0.0.1:8000'

export function getApiBaseUrl() {
	const raw = import.meta.env.VITE_API_URL
	if (raw == null || String(raw).trim() === '') {
		throw new ApiError(
			`VITE_API_URL is not configured. For local development set frontend/.env to VITE_API_URL=${LOCAL_API_URL_HINT}`,
			{ code: 'missing_api_url' },
		)
	}
	return String(raw).trim().replace(/\/$/, '')
}

function buildUrl(path) {
	const base = getApiBaseUrl()
	if (!path) return base
	return `${base}${path.startsWith('/') ? path : `/${path}`}`
}

async function readBody(response) {
	const contentType = response.headers.get('content-type') || ''
	if (contentType.includes('application/json')) {
		try {
			return await response.json()
		} catch {
			throw new ApiError('Server returned invalid JSON.', {
				status: response.status,
				code: 'invalid_json',
			})
		}
	}

	const text = await response.text()
	return text ? { detail: text } : null
}

function messageForStatus(status, detail) {
	if (typeof detail === 'string' && detail.trim()) return detail
	if (detail && typeof detail === 'object') {
		if (typeof detail.detail === 'string') return detail.detail
		if (Array.isArray(detail.detail) && detail.detail[0]?.msg) {
			return detail.detail.map((item) => item.msg).join('; ')
		}
	}

	if (status === 400) return 'The request was invalid.'
	if (status === 401) return 'Authentication is required.'
	if (status === 403) return 'You do not have permission to do that.'
	if (status === 404) return 'The requested resource was not found.'
	if (status === 422) return 'The request could not be processed.'
	if (status === 429) return 'Too many requests. Please try again shortly.'
	if (status >= 500) return 'The server encountered an error. Please try again.'
	return `Request failed (${status}).`
}

/**
 * Low-level JSON request helper.
 * @param {string} path - Path beginning with `/`, e.g. `/health`
 * @param {{ method?: string, body?: unknown, headers?: Record<string, string>, signal?: AbortSignal }} [options]
 */
export async function apiRequest(path, options = {}) {
	const { method = 'GET', body, headers = {}, signal } = options
	const url = buildUrl(path)

	const finalHeaders = { Accept: 'application/json', ...headers }
	let payload = body
	if (body != null && !(body instanceof FormData)) {
		finalHeaders['Content-Type'] = finalHeaders['Content-Type'] || 'application/json'
		payload = typeof body === 'string' ? body : JSON.stringify(body)
	}

	let response
	try {
		response = await fetch(url, {
			method,
			headers: finalHeaders,
			body: method === 'GET' || method === 'HEAD' ? undefined : payload,
			signal,
		})
	} catch (error) {
		if (error?.name === 'AbortError') throw error
		throw new ApiError(
			`Unable to reach the backend at ${getApiBaseUrl()}. Check that the API is running and VITE_API_URL is correct.`,
			{ code: 'network_error' },
		)
	}

	const data = await readBody(response)

	if (!response.ok) {
		throw new ApiError(messageForStatus(response.status, data), {
			status: response.status,
			code: 'http_error',
			details: data,
		})
	}

	return data
}

export const api = {
	get: (path, options = {}) => apiRequest(path, { ...options, method: 'GET' }),
	post: (path, body, options = {}) => apiRequest(path, { ...options, method: 'POST', body }),
	put: (path, body, options = {}) => apiRequest(path, { ...options, method: 'PUT', body }),
	patch: (path, body, options = {}) => apiRequest(path, { ...options, method: 'PATCH', body }),
	delete: (path, options = {}) => apiRequest(path, { ...options, method: 'DELETE' }),
}

/** Development / connection smoke check — calls GET /health only. */
export async function healthCheck() {
	return api.get('/health')
}
