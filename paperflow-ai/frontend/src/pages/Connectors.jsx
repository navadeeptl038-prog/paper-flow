import { useState } from 'react'
import { ArrowUpRight, ShieldCheck } from 'lucide-react'
import ConnectorCard from '../components/ConnectorCard'

const initial = [
	{ name: 'Local Storage', connected: true, account: 'Your private PaperFlow library', description: "PaperFlow's secure remote storage for uploaded documents." },
	{ name: 'Google Drive', connected: true, account: 'aarav@example.com', description: 'Search across files and folders you have chosen to share.' },
	{ name: 'Gmail', connected: false, description: 'Find attachments and relevant messages from your inbox.' },
]

export default function Connectors() {
	const [connectors, setConnectors] = useState(initial)
	const toggle = (name) => setConnectors(connectors.map((item) => item.name === name ? { ...item, connected: !item.connected, account: !item.connected ? 'aarav@example.com' : undefined } : item))
	return <div className="content-page connectors-page"><div className="page-heading"><div><span className="eyebrow">Search everywhere</span><h1>Connected sources</h1><p>Give PaperFlow context without moving your files around.</p></div><div className="privacy-note"><ShieldCheck size={16} /> Your connections are private</div></div><div className="connector-list">{connectors.map((connector) => <ConnectorCard key={connector.name} connector={connector} onToggle={toggle} />)}</div><div className="connector-footer"><div><strong>More sources, better answers</strong><span>PaperFlow only reads what you choose to connect.</span></div><button className="text-button">View privacy details <ArrowUpRight size={15} /></button></div></div>
}
