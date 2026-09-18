export default function UploadProgress({ name = 'document.pdf', progress = 72 }) {
	return <div className="upload-progress"><div className="upload-progress-head"><span>{name}</span><strong>{progress}%</strong></div><div className="progress-track"><span style={{ width: `${progress}%` }} /></div><small>Preparing your document for search...</small></div>
}
