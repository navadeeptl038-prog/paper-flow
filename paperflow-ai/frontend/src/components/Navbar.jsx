import { FileText, FolderOpen, Link2, Menu, MessageCircle, Search, Settings, Sparkles } from 'lucide-react'
import UserMenu from './UserMenu'

export default function Navbar({ onMenu, onNavigate, home = false }) {
	const homeLinks = [
		['home', 'Home', Sparkles],
		['chat', 'Chat', MessageCircle],
		['documents', 'Documents', FileText],
		['connectors', 'Connectors', Link2],
		['settings', 'Settings', Settings],
	]

	return (
		<header className="topbar">
			<button className="icon-button mobile-menu" onClick={onMenu} aria-label="Open navigation" type="button">
				<Menu size={20} />
			</button>
			<button className={`mobile-brand ${home ? 'home-brand' : ''}`} onClick={() => onNavigate('home')} type="button">
				<span className="brand-mark"><Sparkles size={15} /></span>
				PaperFlow <span className="brand-ai">AI</span>
			</button>
			{home && (
				<nav className="home-nav" aria-label="Workspace navigation">
					{homeLinks.map(([id, label, Icon]) => (
						<button key={id} className={id === 'home' ? 'active' : ''} onClick={() => onNavigate(id)} type="button">
							<Icon size={14} />
							{label}
						</button>
					))}
				</nav>
			)}
			<div className="topbar-search">
				<Search size={17} />
				<span>Ask anything about your files</span>
				<kbd>/</kbd>
			</div>
			<div className="topbar-actions">
				<span className="status-pill"><span className="status-dot" /> All systems ready</span>
				<UserMenu />
			</div>
		</header>
	)
}
