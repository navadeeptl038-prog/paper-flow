import { useState } from 'react'
import { FilePlus, Filter, Search } from 'lucide-react'
import DocumentCard from '../components/DocumentCard'
import FileUpload from '../components/FileUpload'
import UploadProgress from '../components/UploadProgress'

const initialDocuments = [
	{ id: 1, filename: 'passport_scan.pdf', type: 'PDF', size: '2.4 MB', source: 'Local Storage', status: 'Ready' },
	{ id: 2, filename: 'bank_statement_may.pdf', type: 'PDF', size: '1.1 MB', source: 'Google Drive', status: 'Ready' },
	{ id: 3, filename: 'rental_agreement.docx', type: 'DOCX', size: '840 KB', source: 'Local Storage', status: 'Indexing' },
	{ id: 4, filename: 'flight_confirmation.png', type: 'PNG', size: '420 KB', source: 'Gmail', status: 'Ready' },
]

export default function Documents() {
	const [documents, setDocuments] = useState(initialDocuments)
	const [query, setQuery] = useState('')
	const [uploading, setUploading] = useState(false)
	const filtered = documents.filter((doc) => doc.filename.toLowerCase().includes(query.toLowerCase()))
	return <div className="content-page"><div className="page-heading"><div><span className="eyebrow">Your library</span><h1>Documents <span className="heading-count">{documents.length}</span></h1><p>Everything PaperFlow can search, organized in one place.</p></div><button className="button primary" onClick={() => setUploading(true)}><FilePlus size={17} /> Add document</button></div>{uploading && <div className="upload-panel"><div><strong>Bring a document into PaperFlow</strong><span>It will appear here once it is ready to search.</span></div><FileUpload onChoose={() => setUploading(false)} /><UploadProgress /></div>}<div className="toolbar"><div className="search-field"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search documents" aria-label="Search documents" /></div><button className="button quiet"><Filter size={16} /> Filter <span>All sources</span></button></div><div className="document-list">{filtered.map((document) => <DocumentCard key={document.id} document={document} onDelete={(id) => setDocuments(documents.filter((item) => item.id !== id))} />)}</div></div>
}
