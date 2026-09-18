import { Download, Ellipsis, Eye, FileText, Trash2 } from 'lucide-react'
import SourceBadge from './SourceBadge'

export default function DocumentCard({ document, onDelete }) {
	return <article className="document-card"><div className="document-icon"><FileText size={22} /></div><div className="document-info"><strong>{document.filename}</strong><span>{document.type} · {document.size}</span><SourceBadge source={document.source} /></div><div className={`doc-status ${document.status.toLowerCase()}`}><span />{document.status}</div><div className="document-actions"><button className="icon-button" title="View" aria-label={`View ${document.filename}`}><Eye size={17} /></button><button className="icon-button" title="Download" aria-label={`Download ${document.filename}`}><Download size={17} /></button>{onDelete && <button className="icon-button danger" title="Delete" aria-label={`Delete ${document.filename}`} onClick={() => onDelete(document.id)}><Trash2 size={17} /></button>}<button className="icon-button more" title="More options" aria-label="More options"><Ellipsis size={18} /></button></div></article>
}
