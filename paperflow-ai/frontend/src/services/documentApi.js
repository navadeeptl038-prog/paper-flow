/**
 * PaperFlow AI — Document API Service (Stage 11)
 *
 * Architecture:
 *   User → Browser → Supabase Storage (paperflow-documents bucket)
 *
 * Direct browser uploads stream files directly to private Supabase Storage
 * under user-scoped paths: <user_id>/<uuid>/<safe_filename>, preventing
 * storage of user files on Render's filesystem.
 *
 * Metadata is stored in PostgreSQL (public.documents table).
 * All operations enforce authenticated identity (auth.uid()).
 */

import { api, getApiBaseUrl, ApiError } from './api'
import { supabase } from './auth'

export const ALLOWED_EXTENSIONS = ['pdf', 'docx', 'jpg', 'jpeg', 'png', 'webp', 'heic', 'heif']
export const MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024 // 50MB

/**
 * Sanitize filename to prevent directory traversal and dangerous characters.
 * @param {string} name
 * @returns {string}
 */
export function sanitizeFilename(name) {
	if (!name) return 'document'
	// Extract basename
	const basename = name.split(/[/\\]/).pop() || 'document'
	// Replace traversal sequences, control characters, and special symbols
	const cleaned = basename
		.replace(/\.\.+/g, '.')
		.replace(/[^a-zA-Z0-9._-]/g, '_')
		.replace(/^_+/, '')
	return cleaned || 'document'
}

/**
 * Infer file category (pdf, docx, image).
 * @param {string} filename
 * @returns {'pdf' | 'docx' | 'image'}
 */
export function inferFileType(filename) {
	const ext = (filename.split('.').pop() || '').toLowerCase()
	if (ext === 'pdf') return 'pdf'
	if (ext === 'docx') return 'docx'
	return 'image'
}

/**
 * Validate a file before upload.
 * @param {File} file
 * @throws {ApiError}
 */
export function validateFile(file) {
	if (!file || !file.name) {
		throw new ApiError('Invalid file: Missing name.', { status: 400 })
	}

	// Path traversal check
	if (file.name.includes('../') || file.name.includes('..\\')) {
		throw new ApiError('Path traversal characters are strictly prohibited in filenames.', { status: 400 })
	}

	const parts = file.name.split('.')
	if (parts.length < 2) {
		throw new ApiError(`File "${file.name}" has no extension.`, { status: 400 })
	}

	const ext = parts.pop().toLowerCase()
	if (!ALLOWED_EXTENSIONS.includes(ext)) {
		throw new ApiError(
			`File type ".${ext}" is not supported. Supported formats: PDF, DOCX, JPG, JPEG, PNG, WEBP, HEIC, HEIF.`,
			{ status: 400 }
		)
	}

	if (file.size <= 0) {
		throw new ApiError(`File "${file.name}" is empty (0 bytes).`, { status: 400 })
	}

	if (file.size > MAX_FILE_SIZE_BYTES) {
		throw new ApiError(
			`File "${file.name}" exceeds the maximum allowed size of 50 MB.`,
			{ status: 400 }
		)
	}
}

export const documentService = {
	/**
	 * List all documents owned by the authenticated user.
	 * @param {string|null} [token]
	 */
	list: async (token) => {
		return api.get('/api/documents', { token })
	},

	/**
	 * Get details for a single document.
	 * @param {string} id
	 * @param {string|null} [token]
	 */
	get: async (id, token) => {
		return api.get(`/api/documents/${id}`, { token })
	},

	/**
	 * Delete a document and its storage object.
	 * @param {string} id
	 * @param {string|null} [token]
	 */
	remove: async (id, token) => {
		return api.delete(`/api/documents/${id}`, { token })
	},

	/**
	 * Query documents matching user intent (e.g. "Find my passport.", "Find my ATM card.").
	 * @param {string} query
	 * @param {string|null} [token]
	 * @returns {Promise<{ query: string, intent: string, found: boolean, documents: any[], count: number }>}
	 */
	query: async (query, token) => {
		return api.get(`/api/documents/query?q=${encodeURIComponent(query)}`, { token })
	},

	/**
	 * Obtain short-lived signed access URLs for preview and download.
	 * @param {string} id
	 * @param {number} [expiresIn] Seconds to live (default: 300)
	 * @param {string|null} [token]
	 */
	getSignedAccess: async (id, expiresIn = 300, token) => {
		return api.post(`/api/documents/${id}/signed-access?expires_in=${expiresIn}`, {}, { token })
	},

	/**
	 * View document in browser preview (PDF/image inline; DOCX safe download fallback).
	 * Uses short-lived signed URL or authenticated streaming.
	 * @param {string} id
	 * @param {string|null} [token]
	 */
	view: async (id, token) => {
		try {
			const res = await api.post(`/api/documents/${id}/signed-access?expires_in=300`, {}, { token })
			if (res && res.view_url) {
				const baseUrl = getApiBaseUrl()
				const fullUrl = res.view_url.startsWith('http') ? res.view_url : `${baseUrl}${res.view_url}`
				window.open(fullUrl, '_blank', 'noopener,noreferrer')
				return { url: fullUrl }
			}
		} catch (err) {
			console.warn('Signed access URL generation fallback to stream:', err)
		}

		// Fallback: authenticated stream blob
		const baseUrl = getApiBaseUrl()
		const res = await fetch(`${baseUrl}/api/documents/${id}/view`, {
			headers: token ? { Authorization: `Bearer ${token}` } : {},
		})
		if (!res.ok) {
			throw new ApiError(`Failed to view document (${res.status})`, { status: res.status })
		}
		const blob = await res.blob()
		const objectUrl = URL.createObjectURL(blob)
		window.open(objectUrl, '_blank', 'noopener,noreferrer')
		return { url: objectUrl }
	},

	/**
	 * Download original document with strict ownership enforcement.
	 * @param {string} id
	 * @param {string} [filename]
	 * @param {string|null} [token]
	 */
	download: async (id, filename = 'document', token) => {
		const baseUrl = getApiBaseUrl()
		const res = await fetch(`${baseUrl}/api/documents/${id}/download`, {
			headers: token ? { Authorization: `Bearer ${token}` } : {},
		})
		if (!res.ok) {
			throw new ApiError(`Failed to download document (${res.status})`, { status: res.status })
		}
		const blob = await res.blob()
		const objectUrl = URL.createObjectURL(blob)
		const link = document.createElement('a')
		link.href = objectUrl
		link.download = filename || 'document'
		document.body.appendChild(link)
		link.click()
		document.body.removeChild(link)
		setTimeout(() => URL.revokeObjectURL(objectUrl), 10000)
		return true
	},

	/**
	 * Upload files.
	 *
	 * Architecture:
	 *   1. Direct Browser → Supabase Storage (paperflow-documents)
	 *      Path: <user_id>/<uuid>/<safe_filename>
	 *   2. Saves metadata in PostgreSQL documents table
	 *   3. Fallback: Streams through backend /api/documents/upload
	 *
	 * @param {File[]|FileList} files
	 * @param {string|null} token
	 * @param {((progress: number) => void)} [onProgress] Progress callback (0-100)
	 * @returns {Promise<{ documents: any[], count: number, message: string }>}
	 */
	upload: async (files, token, onProgress) => {
		const fileList = Array.from(files)
		if (fileList.length === 0) {
			throw new ApiError('No files selected for upload.', { status: 400 })
		}

		// 1. Validate all files first
		for (const file of fileList) {
			validateFile(file)
		}

		// 2. Try direct Browser → Supabase Storage upload
		try {
			const { data: sessionData } = await supabase.auth.getSession()
			const currentUser = sessionData?.session?.user

			if (currentUser && currentUser.id) {
				const uploadedDocuments = []
				const totalFiles = fileList.length

				for (let i = 0; i < totalFiles; i++) {
					const file = fileList[i]
					const docId = crypto.randomUUID ? crypto.randomUUID() : `doc-${Date.now()}-${i}`
					const safeName = sanitizeFilename(file.name)
					// User-scoped path: <user_id>/<uuid>/<safe_filename>
					const storagePath = `${currentUser.id}/${docId}/${safeName}`

					// Report initial progress for this file
					if (onProgress) {
						onProgress(Math.round((i / totalFiles) * 80))
					}

					// Upload directly to private Supabase Storage
					const { data: storageData, error: storageErr } = await supabase.storage
						.from('paperflow-documents')
						.upload(storagePath, file, {
							cacheControl: '3600',
							upsert: false,
							contentType: file.type || 'application/octet-stream',
						})

					if (storageErr) {
						throw storageErr
					}

					// Record document metadata in PostgreSQL
					const docRow = {
						id: docId,
						owner_id: currentUser.id,
						original_filename: file.name,
						storage_path: storagePath,
						file_type: inferFileType(file.name),
						processing_status: 'uploaded', // Acceptable: uploaded/pending. Never 'ready'.
						source: 'local_upload',
						metadata: {
							file_size_bytes: file.size,
							mime_type: file.type || 'application/octet-stream',
							extension: (file.name.split('.').pop() || '').toLowerCase(),
						},
						created_at: new Date().toISOString(),
						updated_at: new Date().toISOString(),
					}

					const { data: insertedData, error: dbErr } = await supabase
						.from('documents')
						.insert(docRow)
						.select()
						.single()

					if (dbErr) {
						// Even if table insert via Supabase client fails, we can register it via backend
						throw dbErr
					}

					uploadedDocuments.push(insertedData || docRow)
				}

				if (onProgress) onProgress(100)

				return {
					documents: uploadedDocuments,
					count: uploadedDocuments.length,
					message: `Successfully uploaded ${uploadedDocuments.length} document(s) directly to secure storage.`,
				}
			}
		} catch (directUploadErr) {
			// If direct browser-to-storage upload encountered an error (e.g. bucket policy or postgrest rule),
			// fall back seamlessly to backend stream upload without interrupting the user.
			console.warn('Direct Supabase storage upload falling back to backend stream:', directUploadErr)
		}

		// 3. Fallback: Stream directly to Supabase via backend API
		const formData = new FormData()
		fileList.forEach((file) => {
			formData.append('files', file)
		})

		const baseUrl = getApiBaseUrl()
		const uploadUrl = `${baseUrl}/api/documents/upload`

		return new Promise((resolve, reject) => {
			const xhr = new XMLHttpRequest()
			xhr.open('POST', uploadUrl, true)
			xhr.responseType = 'json'

			if (token) {
				xhr.setRequestHeader('Authorization', `Bearer ${token}`)
			}
			xhr.setRequestHeader('Accept', 'application/json')

			if (xhr.upload && onProgress) {
				xhr.upload.onprogress = (event) => {
					if (event.lengthComputable) {
						const percent = Math.round((event.loaded / event.total) * 100)
						onProgress(percent)
					}
				}
			}

			xhr.onload = () => {
				if (xhr.status >= 200 && xhr.status < 300) {
					resolve(xhr.response || { documents: [], count: 0 })
				} else {
					const errorDetail =
						xhr.response?.detail ||
						xhr.response?.message ||
						`Upload failed with status ${xhr.status}`
					reject(new ApiError(errorDetail, { status: xhr.status, details: xhr.response }))
				}
			}

			xhr.onerror = () => {
				reject(new ApiError('Network error during file upload.', { status: 0 }))
			}

			xhr.ontimeout = () => {
				reject(new ApiError('File upload timed out.', { status: 408 }))
			}

			xhr.send(formData)
		})
	},
}
