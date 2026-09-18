/**
 * Lightweight frontend structure smoke check.
 * Does not require a browser or unit-test runner.
 */
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const required = [
	'package.json',
	'index.html',
	'vite.config.js',
	'src/main.jsx',
	'src/App.jsx',
	'src/index.css',
	'src/services/api.js',
]

const missing = required.filter((rel) => !existsSync(join(root, rel)))
if (missing.length) {
	console.error('Frontend structure check failed. Missing:')
	for (const file of missing) console.error(`  - ${file}`)
	process.exit(1)
}

const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'))
for (const script of ['dev', 'build', 'preview', 'test', 'test:build', 'test:structure', 'test:health']) {
	if (!pkg.scripts?.[script]) {
		console.error(`Frontend package.json missing script: ${script}`)
		process.exit(1)
	}
}

const apiSource = readFileSync(join(root, 'src/services/api.js'), 'utf8')
for (const token of ['healthCheck', 'VITE_API_URL', 'apiRequest', 'getApiBaseUrl', 'ApiError']) {
	if (!apiSource.includes(token)) {
		console.error(`api.js must define/use ${token}`)
		process.exit(1)
	}
}

if (/VITE_API_URL\s*\|\|\s*['"]http/.test(apiSource) || /fallback.*localhost/i.test(apiSource)) {
	console.error('api.js must not hardcode a localhost fallback for VITE_API_URL')
	process.exit(1)
}

console.log('Frontend structure check passed.')
