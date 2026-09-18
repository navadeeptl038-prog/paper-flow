import { HardDrive, Mail, Search } from 'lucide-react'

export default function SourceBadge({ source = 'Local Storage' }) {
	const normalized = (source || 'Local Storage')
		.replace(/_/g, ' ')
		.replace(/\b\w/g, (c) => c.toUpperCase())
	const Icon = normalized === 'Gmail' ? Mail : normalized === 'Google Drive' ? HardDrive : Search
	return <span className="source-badge"><Icon size={12} />{normalized}</span>
}
