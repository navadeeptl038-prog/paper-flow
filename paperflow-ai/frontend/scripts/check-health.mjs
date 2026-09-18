/**
 * Calls the live backend /health endpoint using VITE_API_URL from frontend/.env.
 * Used for Stage 7 connection verification — not a fake response.
 */
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const envPath = join(root, '.env')

function readViteApiUrl() {
	if (!existsSync(envPath)) {
		throw new Error(
			'frontend/.env is missing. Create it with VITE_API_URL=http://127.0.0.1:8000 for local development.',
		)
	}
	const text = readFileSync(envPath, 'utf8')
	for (const line of text.split(/\r?\n/)) {
		const trimmed = line.trim()
		if (!trimmed || trimmed.startsWith('#')) continue
		const match = trimmed.match(/^VITE_API_URL\s*=\s*(.*)$/)
		if (match) {
			return match[1].trim().replace(/^["']|["']$/g, '').replace(/\/$/, '')
		}
	}
	throw new Error('VITE_API_URL is not set in frontend/.env')
}

const base = readViteApiUrl()
const url = `${base}/health`

let response
try {
	response = await fetch(url, { headers: { Accept: 'application/json' } })
} catch (error) {
	console.error(`Health check failed: unable to reach ${url}`)
	console.error(error?.message || error)
	process.exit(1)
}

let body
try {
	body = await response.json()
} catch {
	console.error(`Health check failed: invalid JSON from ${url} (HTTP ${response.status})`)
	process.exit(1)
}

if (!response.ok) {
	console.error(`Health check failed: HTTP ${response.status}`, body)
	process.exit(1)
}

if (body?.status !== 'ok') {
	console.error('Health check failed: unexpected payload', body)
	process.exit(1)
}

console.log(`Frontend→backend health OK: ${url} → ${JSON.stringify(body)}`)
