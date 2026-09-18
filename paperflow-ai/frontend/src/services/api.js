const apiUrl = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')

export async function healthCheck() {
	if (!apiUrl) {
		throw new Error('VITE_API_URL is not configured')
	}

	let response
	try {
		response = await fetch(`${apiUrl}/health`)
	} catch {
		throw new Error('Unable to reach the backend')
	}

	if (!response.ok) {
		throw new Error(`Backend health check failed (${response.status})`)
	}

	return response.json()
}

export const api = {
	get: (value) => Promise.resolve(value),
	post: (value) => Promise.resolve(value),
}
