import React, { useState } from 'react'
import { Download, Ellipsis, Eye, FileText, Loader2, Trash2 } from 'lucide-react'
import SourceBadge from './SourceBadge'
import { documentService } from '../services/documentApi'

export default function DocumentCard({ document, onView, onDownload, onDelete }) {
	const [isLoadingView, setIsLoadingView] = useState(false)
	const [isLoadingDownload, setIsLoadingDownload] = useState(false)

	if (!document) return null

	const filename = document.filename || document.original_filename || 'Untitled Document'
	const source = document.source || 'Local Storage'
	const type = (document.type || document.file_type || 'file').toUpperCase()
	const status = document.status || document.processing_status || 'Ready'
	const size = document.size || (document.metadata?.file_size_bytes ? `${Math.round(document.metadata.file_size_bytes / 1024)} KB` : '')

	const handleView = async (e) => {
		e.stopPropagation()
		if (onView) {
			return onView(document)
		}
		try {
			setIsLoadingView(true)
			await documentService.view(document.id)
		} catch (err) {
			console.error('View error:', err)
		} finally {
			setIsLoadingView(false)
		}
	}

	const handleDownload = async (e) => {
		e.stopPropagation()
		if (onDownload) {
			return onDownload(document)
		}
		try {
			setIsLoadingDownload(true)
			await documentService.download(document.id, filename)
		} catch (err) {
			console.error('Download error:', err)
		} finally {
			setIsLoadingDownload(false)
		}
	}

	return (
		<article className="document-card" data-testid={`document-card-${document.id}`}>
			<div className="document-icon">
				<FileText size={22} />
			</div>
			<div className="document-info">
				<strong title={filename} className="document-title">{filename}</strong>
				<span className="document-meta">
					{type} {size ? `· ${size}` : ''}
				</span>
				<SourceBadge source={source} />
			</div>
			<div className={`doc-status ${status.toLowerCase()}`}>
				<span />
				{status}
			</div>
			<div className="document-actions">
				<button
					type="button"
					className="icon-button"
					title="View"
					aria-label={`View ${filename}`}
					onClick={handleView}
					disabled={isLoadingView}
				>
					{isLoadingView ? <Loader2 size={17} className="animate-spin" /> : <Eye size={17} />}
				</button>
				<button
					type="button"
					className="icon-button"
					title="Download"
					aria-label={`Download ${filename}`}
					onClick={handleDownload}
					disabled={isLoadingDownload}
				>
					{isLoadingDownload ? <Loader2 size={17} className="animate-spin" /> : <Download size={17} />}
				</button>
				{onDelete && (
					<button
						type="button"
						className="icon-button danger"
						title="Delete"
						aria-label={`Delete ${filename}`}
						onClick={() => onDelete(document.id)}
					>
						<Trash2 size={17} />
					</button>
				)}
				<button
					type="button"
					className="icon-button more"
					title="More options"
					aria-label="More options"
				>
					<Ellipsis size={18} />
				</button>
			</div>
		</article>
	)
}
