import React, { useState } from 'react'
import {
	AlertCircle,
	Check,
	CheckCircle2,
	ChevronDown,
	ChevronUp,
	Download,
	Eye,
	FileText,
	HelpCircle,
	Info,
	Loader2,
	ShieldCheck,
	XCircle,
} from 'lucide-react'
import SourceBadge from './SourceBadge'
import { documentService } from '../services/documentApi'

export default function RequirementChecklist({
	checklist,
	items = [],
	onView,
	onDownload,
	onClarify,
}) {
	const [expandedDuplicates, setExpandedDuplicates] = useState({})
	const [loadingActionId, setLoadingActionId] = useState(null)

	// Support either full checklist object or items array
	const normalizedItems = checklist?.items || items || []
	const disclaimer =
		checklist?.disclaimer ||
		'Note: These requirements are compiled for guidance based on standard checklists and do not constitute an official government determination. Please consult the official embassy or consulate website for definitive requirements.'
	const authoritativeSource = checklist?.authoritative_source
	const requiresClarification = checklist?.requires_clarification
	const clarificationPrompt = checklist?.clarification_prompt
	const summary = checklist?.summary

	const presentCount = normalizedItems.filter(
		(i) => i.status === 'present' || i.present === true
	).length
	const missingCount = normalizedItems.length - presentCount
	const allPresent = normalizedItems.length > 0 && missingCount === 0
	const noneFound = normalizedItems.length > 0 && presentCount === 0

	const toggleDuplicates = (name) => {
		setExpandedDuplicates((prev) => ({ ...prev, [name]: !prev[name] }))
	}

	const handleView = async (doc) => {
		if (onView) return onView(doc)
		try {
			setLoadingActionId(`view-${doc.id}`)
			await documentService.view(doc.id)
		} catch (err) {
			console.error('Failed to view document:', err)
		} finally {
			setLoadingActionId(null)
		}
	}

	const handleDownload = async (doc) => {
		if (onDownload) return onDownload(doc)
		try {
			setLoadingActionId(`download-${doc.id}`)
			await documentService.download(doc.id, doc.filename || doc.original_filename)
		} catch (err) {
			console.error('Failed to download document:', err)
		} finally {
			setLoadingActionId(null)
		}
	}

	return (
		<div className="requirement-checker-card" data-testid="requirement-checklist">
			{/* Header with summary and readiness badges */}
			<div className="requirement-header">
				<div className="requirement-title-group">
					<h3 className="requirement-heading">
						<ShieldCheck size={20} className="header-icon" />
						Document Requirements Checklist
					</h3>
					{summary && <p className="requirement-summary-text">{summary}</p>}
				</div>

				<div className="requirement-stats">
					<span className={`stat-badge ${allPresent ? 'success' : noneFound ? 'danger' : 'warning'}`}>
						{allPresent ? (
							<>
								<CheckCircle2 size={14} /> All Required Present
							</>
						) : noneFound ? (
							<>
								<XCircle size={14} /> None Found
							</>
						) : (
							<>
								<AlertCircle size={14} /> {presentCount} Present · {missingCount} Missing
							</>
						)}
					</span>
				</div>
			</div>

			{/* Clarification prompt if country / purpose is needed */}
			{requiresClarification && clarificationPrompt && (
				<div className="requirement-clarification-box" data-testid="clarification-prompt">
					<div className="clarification-header">
						<HelpCircle size={16} />
						<strong>Destination & Purpose Details Needed</strong>
					</div>
					<p>{clarificationPrompt}</p>
					{onClarify && (
						<div className="quick-destination-chips">
							{['US Tourist', 'Schengen Area', 'UK Visitor', 'Canada Tourist'].map((dest) => (
								<button
									key={dest}
									type="button"
									className="destination-chip"
									onClick={() => onClarify(dest)}
								>
									{dest}
								</button>
							))}
						</div>
					)}
				</div>
			)}

			{/* Authoritative source citation if available */}
			{authoritativeSource && (
				<div className="authoritative-source-badge" data-testid="authoritative-source">
					<ShieldCheck size={14} />
					<span>
						<strong>Authoritative Reference:</strong> {authoritativeSource}
					</span>
				</div>
			)}

			{/* Checklist Items */}
			<div className="requirement-list">
				{normalizedItems.map((item) => {
					const isPresent = item.status === 'present' || item.present === true
					const doc = item.matched_document || item.document || (isPresent ? { filename: item.file || item.filename, source: item.source || 'Local Storage', id: item.id } : null)
					const duplicates = item.duplicates || []
					const hasDuplicates = duplicates.length > 0
					const isExpanded = !!expandedDuplicates[item.name || item.label]

					return (
						<div
							className={`requirement-item ${isPresent ? 'present' : 'missing'}`}
							key={item.name || item.label}
							data-testid={`requirement-item-${(item.name || item.label).toLowerCase().replace(/\s+/g, '-')}`}
						>
							<div className="item-status-icon">
								{isPresent ? (
									<span className="check-icon" title="Present">
										<Check size={14} />
									</span>
								) : (
									<span className="missing-icon" title="Missing">
										<XCircle size={15} />
									</span>
								)}
							</div>

							<div className="item-content">
								<div className="item-main">
									<strong className="item-name">{item.name || item.label}</strong>
									<span className={`status-pill ${isPresent ? 'present' : 'missing'}`}>
										{isPresent ? 'Present' : 'Missing'}
									</span>
								</div>

								{item.description && (
									<p className="item-description">{item.description}</p>
								)}

								{/* Present Document Details */}
								{isPresent && doc && (
									<div className="matched-doc-info">
										<FileText size={15} className="file-icon" />
										<span className="doc-filename" title={doc.filename}>
											{doc.filename}
										</span>
										<SourceBadge source={doc.source || 'Local Storage'} />

										{/* Duplicate indicator */}
										{hasDuplicates && (
											<button
												type="button"
												className="duplicate-toggle-btn"
												onClick={() => toggleDuplicates(item.name || item.label)}
											>
												+{duplicates.length} other {duplicates.length === 1 ? 'copy' : 'copies'}
												{isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
											</button>
										)}
									</div>
								)}

								{/* Missing Document Notice */}
								{!isPresent && (
									<p className="missing-notice">
										Missing · Not found in your documents or connected sources
									</p>
								)}

								{/* Collapsible Duplicates List */}
								{isPresent && hasDuplicates && isExpanded && (
									<div className="duplicates-list">
										<span className="duplicates-title">Additional matching copies:</span>
										{duplicates.map((dup) => (
											<div key={dup.id} className="duplicate-row">
												<FileText size={13} />
												<span className="duplicate-filename">{dup.filename}</span>
												<SourceBadge source={dup.source || 'Local Storage'} />
												<div className="item-actions mini">
													<button
														type="button"
														className="action-btn view"
														title={`View ${dup.filename}`}
														aria-label={`View ${dup.filename}`}
														onClick={() => handleView(dup)}
													>
														<Eye size={13} />
													</button>
													<button
														type="button"
														className="action-btn download"
														title={`Download ${dup.filename}`}
														aria-label={`Download ${dup.filename}`}
														onClick={() => handleDownload(dup)}
													>
														<Download size={13} />
													</button>
												</div>
											</div>
										))}
									</div>
								)}
							</div>

							{/* Actions: ONLY displayed for Present documents, NEVER for Missing */}
							{isPresent && doc && (
								<div className="item-actions">
									<button
										type="button"
										className="action-btn view"
										title={`View ${doc.filename}`}
										aria-label={`View ${doc.filename}`}
										onClick={() => handleView(doc)}
										disabled={loadingActionId === `view-${doc.id}`}
									>
										{loadingActionId === `view-${doc.id}` ? (
											<Loader2 size={15} className="animate-spin" />
										) : (
											<>
												<Eye size={15} />
												<span>View</span>
											</>
										)}
									</button>

									<button
										type="button"
										className="action-btn download"
										title={`Download ${doc.filename}`}
										aria-label={`Download ${doc.filename}`}
										onClick={() => handleDownload(doc)}
										disabled={loadingActionId === `download-${doc.id}`}
									>
										{loadingActionId === `download-${doc.id}` ? (
											<Loader2 size={15} className="animate-spin" />
										) : (
											<>
												<Download size={15} />
												<span>Download</span>
											</>
										)}
									</button>
								</div>
							)}
						</div>
					)
				})}
			</div>

			{/* Non-official Disclaimer */}
			<div className="requirement-disclaimer" data-testid="disclaimer">
				<Info size={14} className="disclaimer-icon" />
				<p>{disclaimer}</p>
			</div>
		</div>
	)
}
