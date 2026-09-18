import { FileUp } from 'lucide-react'

export default function FileUpload({ onChoose }) {
	return <button className="dropzone" onClick={onChoose}><FileUp size={22} /><span>Drop a file here or browse</span><small>PDF, DOCX, JPG, PNG, WEBP, HEIC</small></button>
}
