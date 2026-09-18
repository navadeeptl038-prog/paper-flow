import { Check, ExternalLink, HardDrive, Mail, Unplug } from 'lucide-react'

const icons = { 'Google Drive': HardDrive, Gmail: Mail, 'Local Storage': HardDrive }

export default function ConnectorCard({ connector, onToggle }) {
	const Icon = icons[connector.name] || HardDrive
	return <article className="connector-card"><div className={`connector-logo ${connector.name === 'Gmail' ? 'gmail' : ''}`}><Icon size={22} /></div><div className="connector-info"><div><strong>{connector.name}</strong><span className={`connector-state ${connector.connected ? 'connected' : ''}`}><span />{connector.connected ? 'Connected' : 'Not connected'}</span></div><p>{connector.description}</p>{connector.account && <small>{connector.account}</small>}</div><button className={`connector-action ${connector.connected ? 'connected-action' : ''}`} onClick={() => onToggle?.(connector.name)}>{connector.connected ? <><Check size={15} /> Connected</> : <><ExternalLink size={15} /> Connect</>}</button></article>
}
