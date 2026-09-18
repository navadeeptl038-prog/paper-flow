import { HardDrive, Mail, Search } from 'lucide-react'

export default function SourceBadge({ source = 'Local Storage' }) {
	const Icon = source === 'Gmail' ? Mail : source === 'Google Drive' ? HardDrive : Search
	return <span className="source-badge"><Icon size={12} />{source}</span>
}
