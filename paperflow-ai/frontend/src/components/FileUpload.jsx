import React, { useRef, useState } from 'react'
import { FileUp, AlertTriangle, CheckCircle, RefreshCw } from 'lucide-react'
import useAuth from '../hooks/useAuth'
import { documentService } from '../services/documentApi'
import UploadProgress from './UploadProgress'

const ALLOWED_EXTENSIONS = ['pdf', 'docx', 'jpg', 'jpeg', 'png', 'webp', 'heic', 'heif']
const MAX_FILE_SIZE = 50 * 1024 * 1024 // 50MB in bytes

/**
 * Validates a single file before initiating upload.
 * Returns null if valid, or an error string if invalid.
 */
function validateFile(file) {
	if (!file || !file.name) {
		return 'Invalid file: Missing name.'
	}

	const parts = file.name.split('.')
	if (parts.length < 2) {
		return `File "${file.name}" has no extension.`
	}

	const ext = parts.pop().toLowerCase()
	if (!ALLOWED_EXTENSIONS.includes(ext)) {
		return `Unsupported format ".${ext}" for "${file.name}". Supported: PDF, DOCX, JPG, JPEG, PNG, WEBP, HEIC, HEIF.`
	}

	if (file.size <= 0) {
		return `File "${file.name}" is empty (0 bytes).`
	}

	if (file.size > MAX_FILE_SIZE) {
		const mb = (file.size / (1024 * 1024)).toFixed(1)
		return `File "${file.name}" exceeds the 50MB limit (${mb} MB).`
	}

	return null
}

export default function FileUpload({ onChoose, onUploadSuccess, onUploadError }) {
	const fileInputRef = useRef(null)
	const { getToken, user } = useAuth()

	const [isDragging, setIsDragging] = useState(false)
	const [uploading, setUploading] = useState(false)
	const [progress, setProgress] = useState(0)
	const [status, setStatus] = useState('idle') // 'idle' | 'uploading' | 'uploaded' | 'pending' | 'error'
	const [errorMessage, setErrorMessage] = useState(null)
	const [currentFileName, setCurrentFileName] = useState('')
	const [uploadedCount, setUploadedCount] = useState(0)

	const triggerPicker = () => {
		if (uploading) return
		if (fileInputRef.current) {
			fileInputRef.current.value = ''
			fileInputRef.current.click()
		}
	}

	const handleFiles = async (fileList) => {
		const files = Array.from(fileList || [])
		if (files.length === 0) return

		setErrorMessage(null)

		// 1. Client-side validation
		for (const file of files) {
			const validationErr = validateFile(file)
			if (validationErr) {
				setErrorMessage(validationErr)
				setStatus('error')
				if (onUploadError) onUploadError(new Error(validationErr))
				return
			}
		}

		// 2. Auth check
		const token = await getToken()
		if (!token) {
			const authErr = 'Authentication required. Please log in before uploading documents.'
			setErrorMessage(authErr)
			setStatus('error')
			if (onUploadError) onUploadError(new Error(authErr))
			return
		}

		// 3. Prepare upload UI state
		const displayName =
			files.length === 1
				? files[0].name
				: `${files.length} documents (${files.map((f) => f.name).slice(0, 2).join(', ')}${files.length > 2 ? '...' : ''})`

		setCurrentFileName(displayName)
		setUploading(true)
		setProgress(0)
		setStatus('uploading')

		try {
			const result = await documentService.upload(files, token, (percent) => {
				setProgress(percent)
				if (percent >= 100) {
					setStatus('pending') // Uploaded to storage, awaiting processing
				}
			})

			setProgress(100)
			setStatus('uploaded')
			setUploadedCount(result.count || files.length)

			if (onUploadSuccess) {
				onUploadSuccess(result)
			}
		} catch (err) {
			const message = err?.message || 'Upload failed. Please try again.'
			setErrorMessage(message)
			setStatus('error')
			if (onUploadError) {
				onUploadError(err)
			}
		} finally {
			setUploading(false)
		}
	}

	const onDragOver = (e) => {
		e.preventDefault()
		e.stopPropagation()
		if (!uploading) setIsDragging(true)
	}

	const onDragLeave = (e) => {
		e.preventDefault()
		e.stopPropagation()
		setIsDragging(false)
	}

	const onDrop = (e) => {
		e.preventDefault()
		e.stopPropagation()
		setIsDragging(false)
		if (uploading) return

		if (e.dataTransfer && e.dataTransfer.files) {
			handleFiles(e.dataTransfer.files)
		}
	}

	const onFileInputChange = (e) => {
		if (e.target.files) {
			handleFiles(e.target.files)
		}
	}

	const handleReset = (e) => {
		e.stopPropagation()
		setStatus('idle')
		setErrorMessage(null)
		setProgress(0)
		setCurrentFileName('')
		setUploadedCount(0)
	}

	return (
		<div style={{ display: 'grid', gap: '10px' }}>
			{/* Hidden file input */}
			<input
				ref={fileInputRef}
				type="file"
				multiple
				accept=".pdf,.docx,.jpg,.jpeg,.png,.webp,.heic,.heif,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/jpeg,image/png,image/webp,image/heic,image/heif"
				style={{ display: 'none' }}
				onChange={onFileInputChange}
				disabled={uploading}
			/>

			{/* Drag and Drop Zone */}
			<button
				type="button"
				className="dropzone"
				onClick={triggerPicker}
				onDragOver={onDragOver}
				onDragLeave={onDragLeave}
				onDrop={onDrop}
				disabled={uploading}
				style={{
					cursor: uploading ? 'not-allowed' : 'pointer',
					borderColor: isDragging ? 'var(--coral, #e06c55)' : undefined,
					backgroundColor: isDragging ? 'rgba(224, 108, 85, 0.08)' : undefined,
					transition: 'all 0.2s ease',
					position: 'relative',
					width: '100%',
					outline: 'none',
				}}
			>
				<FileUp size={24} style={{ color: isDragging ? 'var(--coral, #e06c55)' : undefined }} />
				<span>{isDragging ? 'Drop files to upload' : 'Drop files here or click to browse'}</span>
				<small>Supported: PDF, DOCX, JPG, PNG, WEBP, HEIC (Max 50MB each)</small>
			</button>

			{/* Inline Error Display */}
			{errorMessage && (
				<div
					style={{
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'space-between',
						background: '#faebe9',
						border: '1px solid #f0ccc7',
						borderRadius: '8px',
						padding: '8px 12px',
						fontSize: '11px',
						color: '#b54e42',
					}}
				>
					<div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
						<AlertTriangle size={14} />
						<span>{errorMessage}</span>
					</div>
					<button
						type="button"
						onClick={handleReset}
						style={{
							background: 'transparent',
							border: 0,
							color: '#b54e42',
							cursor: 'pointer',
							textDecoration: 'underline',
							fontSize: '10px',
						}}
					>
						Clear
					</button>
				</div>
			)}

			{/* Live Progress & Status Display */}
			{(uploading || status === 'uploaded' || status === 'pending') && (
				<UploadProgress
					name={currentFileName}
					progress={progress}
					status={status}
					error={errorMessage}
					onDismiss={status === 'uploaded' ? handleReset : null}
				/>
			)}

			{/* Upload Success Details & Actions */}
			{status === 'uploaded' && (
				<div
					style={{
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'space-between',
						background: '#edf6ed',
						border: '1px solid #cce5cd',
						borderRadius: '8px',
						padding: '8px 12px',
						fontSize: '11px',
						color: '#3d7a40',
					}}
				>
					<div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
						<CheckCircle size={14} />
						<span>
							{uploadedCount} document{uploadedCount > 1 ? 's' : ''} uploaded to private storage (Status: pending).
						</span>
					</div>
					<div style={{ display: 'flex', gap: '8px' }}>
						<button
							type="button"
							onClick={handleReset}
							style={{
								background: 'transparent',
								border: 0,
								color: '#3d7a40',
								cursor: 'pointer',
								fontSize: '10px',
								textDecoration: 'underline',
								display: 'inline-flex',
								alignItems: 'center',
								gap: '3px',
							}}
						>
							<RefreshCw size={10} /> Upload another
						</button>
						{onChoose && (
							<button
								type="button"
								onClick={onChoose}
								style={{
									background: '#3d7a40',
									color: '#ffffff',
									border: 0,
									borderRadius: '4px',
									padding: '3px 8px',
									fontSize: '10px',
									cursor: 'pointer',
									fontWeight: 600,
								}}
							>
								Done
							</button>
						)}
					</div>
				</div>
			)}
		</div>
	)
}
