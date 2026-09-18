/**
 * PaperFlow AI — Frontend API client (Stage 7)
 *
 * Responsibilities:
 *  - Build request URLs from VITE_API_URL (environment only, no hardcoded URLs)
 *  - Attach JSON headers and optional Bearer token
 *  - Apply a configurable request timeout via AbortSignal
 *  - Parse JSON responses and surface plain-text bodies as { detail }
 *  - Map every HTTP status to a typed ApiError with a predictable shape
 *  - Expose a clean `api` object: get / post / put / patch / delete
 *
 * Rules enforced here:
 *  - No API keys, Gemini keys, service-role keys, OAuth secrets, or passwords
 *  - No hardcoded production URLs
 *  - No second auth system — tokens come from Supabase Auth (Stage 8+)
 *  - No manual localStorage token storage
 */

// ---------------------------------------------------------------------------
// Error class
// ---------------------------------------------------------------------------

/**
 * Structured error thrown by every apiRequest failure.
 *
 * Properties:
 *  - message  {string}        Human-readable description safe to display
 *  - name     {string}        Always 'ApiError'
 *  - status   {number|null}   HTTP status code, or null for network/timeout
 *  - code     {string}        Machine-readable code — see ERROR_CODES below
 *  - details  {unknown}       Raw response body (may be null)
 *  - retryAfter {number|null} Seconds to wait before retrying (429 only)
 */
export class ApiError extends Error {
	/**
	 * @param {string} message
	 * @param {{
	 *   status?:     number|null,
	 *   code?:       string,
	 *   details?:    unknown,
	 *   retryAfter?: number|null
	 * }} [options]
	 */
	constructor(message, { status = null, code = 'api_error', details = null, retryAfter = null } = {}) {
		super(message)
		this.name = 'ApiError'
		this.status = status
		this.code = code
		this.details = details
		this.retryAfter = retryAfter
	}
}

// ---------------------------------------------------------------------------
// Machine-readable error codes
// ---------------------------------------------------------------------------

/**
 * Canonical error codes returned in ApiError.code.
 * Import these in consuming services to avoid magic strings.
 */
export const ERROR_CODES = /** @type {const} */ ({
	MISSING_API_URL:  'missing_api_url',   // VITE_API_URL not configured
	NETWORK_ERROR:    'network_error',      // fetch() threw — server unreachable
	TIMEOUT:          'timeout',            // request exceeded DEFAULT_TIMEOUT_MS
	INVALID_JSON:     'invalid_json',       // server replied with non-JSON body
	BAD_REQUEST:      'bad_request',        // 400
	UNAUTHORIZED:     'unauthorized',       // 401
	FORBIDDEN:        'forbidden',          // 403
	NOT_FOUND:        'not_found',          // 404
	UNPROCESSABLE:    'unprocessable',      // 422
	RATE_LIMITED:     'rate_limited',       // 429
	SERVER_ERROR:     'server_error',       // 5xx
	HTTP_ERROR:       'http_error',         // any other non-2xx
})

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

/**
 * Default request timeout in milliseconds.
 * Individual calls can override by passing their own AbortSignal.
 */
export const DEFAULT_TIMEOUT_MS = 15_000

/**
 * Documented hint shown in the missing-URL error.
 * NOT used as a silent runtime fallback.
 */
export const LOCAL_API_URL_HINT = 'http://127.0.0.1:8000'

// ---------------------------------------------------------------------------
// URL helpers
// ---------------------------------------------------------------------------

/**
 * Read and validate VITE_API_URL from Vite's import.meta.env.
 * Also accepts VITE_API_BASE_URL as a secondary name (root .env.example compat).
 *
 * @returns {string} Trimmed base URL with no trailing slash
 * @throws  {ApiError} code=missing_api_url when not configured
 */
export function getApiBaseUrl() {
	const raw = import.meta.env.VITE_API_URL ?? import.meta.env.VITE_API_BASE_URL
	if (raw == null || String(raw).trim() === '') {
		throw new ApiError(
			`VITE_API_URL is not configured. ` +
			`For local development add VITE_API_URL=${LOCAL_API_URL_HINT} to frontend/.env`,
			{ code: ERROR_CODES.MISSING_API_URL },
		)
	}
	return String(raw).trim().replace(/\/$/, '')
}

/**
 * Build an absolute URL for the given API path.
 *
 * @param {string} path  e.g. '/health', '/api/documents'
 * @returns {string}
 */
function buildUrl(path) {
	const base = getApiBaseUrl()
	if (!path) return base
	return `${base}${path.startsWith('/') ? path : `/${path}`}`
}

// ---------------------------------------------------------------------------
// Response parsing
// ---------------------------------------------------------------------------

/**
 * Parse the response body as JSON when the Content-Type is application/json.
 * Falls back to plain text wrapped in { detail }.
 *
 * @param {Response} response
 * @returns {Promise<unknown>}
 * @throws  {ApiError} code=invalid_json when JSON parsing fails
 */
async function readBody(response) {
	const contentType = response.headers.get('content-type') ?? ''

	if (contentType.includes('application/json')) {
		try {
			return await response.json()
		} catch {
			throw new ApiError('The server returned a response that could not be parsed.', {
				status: response.status,
				code:   ERROR_CODES.INVALID_JSON,
			})
		}
	}

	const text = await response.text().catch(() => '')
	return text ? { detail: text } : null
}

// ---------------------------------------------------------------------------
// Status → message + code mapping
// ---------------------------------------------------------------------------

/**
 * Map an HTTP status code to a { message, code } pair.
 * Prefers an explicit 'detail' from the response body over the generic fallback.
 *
 * @param {number}  status
 * @param {unknown} body    Parsed response body (may be null)
 * @returns {{ message: string, code: string, retryAfter: number|null }}
 */
function classifyError(status, body) {
	// Extract a human message from the body when the backend sends one
	let message = ''
	if (typeof body === 'string' && body.trim()) {
		message = body.trim()
	} else if (body && typeof body === 'object') {
		const b = /** @type {Record<string, unknown>} */ (body)
		if (typeof b.detail === 'string' && b.detail.trim()) {
			message = b.detail.trim()
		} else if (Array.isArray(b.detail) && b.detail[0]?.msg) {
			message = b.detail.map((item) => item.msg).join('; ')
		} else if (typeof b.message === 'string' && b.message.trim()) {
			message = b.message.trim()
		}
	}

	/** @type {number|null} */
	let retryAfter = null

	switch (status) {
		case 400:
			return { message: message || 'The request was invalid. Check the data you submitted.', code: ERROR_CODES.BAD_REQUEST, retryAfter }
		case 401:
			return { message: message || 'You must be signed in to do that.', code: ERROR_CODES.UNAUTHORIZED, retryAfter }
		case 403:
			return { message: message || 'You do not have permission to do that.', code: ERROR_CODES.FORBIDDEN, retryAfter }
		case 404:
			return { message: message || 'The requested resource was not found.', code: ERROR_CODES.NOT_FOUND, retryAfter }
		case 422:
			return { message: message || 'The request could not be processed. Check the submitted data.', code: ERROR_CODES.UNPROCESSABLE, retryAfter }
		case 429: {
			// Respect Retry-After if backend sends it (handled in apiRequest via headers)
			return { message: message || 'Too many requests. Please wait a moment and try again.', code: ERROR_CODES.RATE_LIMITED, retryAfter }
		}
		default:
			if (status >= 500) {
				return { message: message || 'The server encountered an error. Please try again shortly.', code: ERROR_CODES.SERVER_ERROR, retryAfter }
			}
			return { message: message || `Request failed with status ${status}.`, code: ERROR_CODES.HTTP_ERROR, retryAfter }
	}
}

// ---------------------------------------------------------------------------
// Core request function
// ---------------------------------------------------------------------------

/**
 * Send an authenticated JSON request to the PaperFlow AI backend.
 *
 * @param {string} path     API path, e.g. '/health' or '/api/documents'
 * @param {{
 *   method?:      string,
 *   body?:        unknown,
 *   headers?:     Record<string, string>,
 *   token?:       string|null,
 *   signal?:      AbortSignal,
 *   timeoutMs?:   number,
 * }} [options]
 *
 * Options:
 *  - method     HTTP verb (default: 'GET')
 *  - body       Request payload; plain objects are JSON-serialised automatically
 *               Pass FormData to send multipart — Content-Type is NOT overridden
 *  - headers    Extra headers merged after defaults
 *  - token      Supabase access token — attached as `Authorization: Bearer <token>`
 *               Obtain from supabase.auth.getSession() in Stage 8+; never store manually
 *  - signal     External AbortSignal (e.g. from a React useEffect cleanup)
 *               The internal timeout signal is combined via AbortSignal.any when available
 *  - timeoutMs  Override the default 15 s timeout (0 = no timeout)
 *
 * @returns {Promise<unknown>} Parsed response body
 * @throws  {ApiError}         On any failure — network, timeout, or HTTP error
 */
export async function apiRequest(path, options = {}) {
	const {
		method    = 'GET',
		body      = undefined,
		headers   = {},
		token     = null,
		signal    = undefined,
		timeoutMs = DEFAULT_TIMEOUT_MS,
	} = options

	const url = buildUrl(path)

	// --- Build headers ---
	/** @type {Record<string, string>} */
	const finalHeaders = { Accept: 'application/json' }

	if (token) {
		finalHeaders['Authorization'] = `Bearer ${token}`
	}

	// Merge caller-supplied headers (allow overriding Accept / Authorization)
	Object.assign(finalHeaders, headers)

	// Serialise body unless it is FormData (multipart) or already a string
	let payload = body
	if (body != null && !(body instanceof FormData)) {
		if (typeof body !== 'string') {
			payload = JSON.stringify(body)
		}
		// Only set Content-Type when not already specified by the caller
		if (!finalHeaders['Content-Type'] && !headers['Content-Type']) {
			finalHeaders['Content-Type'] = 'application/json'
		}
	}

	// --- Timeout signal ---
	/** @type {AbortSignal|undefined} */
	let effectiveSignal = signal

	/** @type {ReturnType<typeof setTimeout>|undefined} */
	let timeoutId

	if (timeoutMs > 0) {
		const timeoutController = new AbortController()
		timeoutId = setTimeout(() => timeoutController.abort(), timeoutMs)

		// Combine caller signal + timeout signal when the browser supports it
		if (signal && typeof AbortSignal.any === 'function') {
			effectiveSignal = AbortSignal.any([signal, timeoutController.signal])
		} else if (signal) {
			// Fallback: forward abort from caller to timeout controller
			signal.addEventListener('abort', () => timeoutController.abort(), { once: true })
			effectiveSignal = timeoutController.signal
		} else {
			effectiveSignal = timeoutController.signal
		}
	}

	// --- Fetch ---
	/** @type {Response} */
	let response
	try {
		response = await fetch(url, {
			method,
			headers: finalHeaders,
			body:    (method === 'GET' || method === 'HEAD') ? undefined : payload,
			signal:  effectiveSignal,
		})
	} catch (fetchError) {
		if (timeoutId !== undefined) clearTimeout(timeoutId)

		// AbortError can mean either a timeout or a caller-triggered abort
		if (fetchError?.name === 'AbortError') {
			// If the caller's own signal is already aborted, re-throw so React
			// useEffect cleanup works correctly without a misleading error message
			if (signal?.aborted) throw fetchError

			throw new ApiError(
				`The request to ${getApiBaseUrl()} timed out after ${timeoutMs / 1000} s. ` +
				`Check your network connection and that the backend is running.`,
				{ code: ERROR_CODES.TIMEOUT },
			)
		}

		throw new ApiError(
			`Unable to reach the backend at ${getApiBaseUrl()}. ` +
			`Check that the API is running and VITE_API_URL is set correctly.`,
			{ code: ERROR_CODES.NETWORK_ERROR },
		)
	} finally {
		if (timeoutId !== undefined) clearTimeout(timeoutId)
	}

	// --- Parse body ---
	const data = await readBody(response)

	// --- Handle non-2xx ---
	if (!response.ok) {
		const { message, code, retryAfter: baseRetryAfter } = classifyError(response.status, data)

		// Parse Retry-After header for 429 responses
		let retryAfter = baseRetryAfter
		if (response.status === 429) {
			const raw = response.headers.get('Retry-After')
			if (raw) {
				const seconds = Number(raw)
				retryAfter = Number.isFinite(seconds) ? seconds : null
			}
		}

		throw new ApiError(message, {
			status: response.status,
			code,
			details: data,
			retryAfter,
		})
	}

	return data
}

// ---------------------------------------------------------------------------
// Convenience API object
// ---------------------------------------------------------------------------

/**
 * Typed shorthand methods wrapping apiRequest.
 *
 * Each method accepts the same `options` object as apiRequest,
 * which includes the optional `token` field for authenticated calls:
 *
 *   const { data: session } = await supabase.auth.getSession()
 *   const token = session?.access_token ?? null
 *   const result = await api.get('/api/documents', { token })
 *
 * Do NOT import or call supabase directly from this file.
 * Token injection is the responsibility of the calling service/hook.
 */
export const api = {
	/**
	 * @param {string} path
	 * @param {Parameters<typeof apiRequest>[1]} [options]
	 */
	get: (path, options = {}) =>
		apiRequest(path, { ...options, method: 'GET' }),

	/**
	 * @param {string}  path
	 * @param {unknown} body
	 * @param {Parameters<typeof apiRequest>[1]} [options]
	 */
	post: (path, body, options = {}) =>
		apiRequest(path, { ...options, method: 'POST', body }),

	/**
	 * @param {string}  path
	 * @param {unknown} body
	 * @param {Parameters<typeof apiRequest>[1]} [options]
	 */
	put: (path, body, options = {}) =>
		apiRequest(path, { ...options, method: 'PUT', body }),

	/**
	 * @param {string}  path
	 * @param {unknown} body
	 * @param {Parameters<typeof apiRequest>[1]} [options]
	 */
	patch: (path, body, options = {}) =>
		apiRequest(path, { ...options, method: 'PATCH', body }),

	/**
	 * @param {string} path
	 * @param {Parameters<typeof apiRequest>[1]} [options]
	 */
	delete: (path, options = {}) =>
		apiRequest(path, { ...options, method: 'DELETE' }),
}

// ---------------------------------------------------------------------------
// Named helper — connection smoke-test
// ---------------------------------------------------------------------------

/**
 * Call GET /health and return the parsed response.
 * Used by the Home page and the check-health.mjs script.
 * Does not require authentication.
 *
 * @returns {Promise<{ status: string }>}
 */
export async function healthCheck() {
	return api.get('/health')
}

// ---------------------------------------------------------------------------
// Chat API helpers (Stage 10)
// ---------------------------------------------------------------------------

export const chatApi = {
	/**
	 * Fetch all conversations for the authenticated user (continuous list).
	 * @param {string|null} token
	 */
	listConversations: (token) =>
		api.get('/api/chat/conversations', { token }),

	/**
	 * Create a new conversation.
	 * @param {{ title?: string }} payload
	 * @param {string|null} token
	 */
	createConversation: (payload = {}, token) =>
		api.post('/api/chat/conversations', payload, { token }),

	/**
	 * Retrieve a conversation and its messages.
	 * @param {string} conversationId
	 * @param {string|null} token
	 */
	getConversation: (conversationId, token) =>
		api.get(`/api/chat/conversations/${conversationId}`, { token }),

	/**
	 * Send a message to a conversation.
	 * @param {string} conversationId
	 * @param {{ content: string, role?: string, sources?: any[] }} payload
	 * @param {string|null} token
	 */
	sendMessage: (conversationId, payload, token) =>
		api.post(`/api/chat/conversations/${conversationId}/messages`, payload, { token }),

	/**
	 * Delete a conversation.
	 * @param {string} conversationId
	 * @param {string|null} token
	 */
	deleteConversation: (conversationId, token) =>
		api.delete(`/api/chat/conversations/${conversationId}`, { token }),
}
