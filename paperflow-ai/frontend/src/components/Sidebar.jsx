import { FileText, FolderOpen, Home, Link2, MessageCircle, Settings, Sparkles, X } from 'lucide-react'

const navItems = [
	{ id: 'home', label: 'Home', icon: Home },
	{ id: 'chat', label: 'Chats', icon: MessageCircle },
	{ id: 'documents', label: 'Documents', icon: FileText },
	{ id: 'connectors', label: 'Connectors', icon: Link2 },
]

export default function Sidebar({ activeRoute, onNavigate, open, onClose }) {
	return (
		<aside className={`sidebar ${open ? 'is-open' : ''}`}>
			<div className="sidebar-head">
				<button className="brand" onClick={() => onNavigate('home')} type="button">
					<span className="brand-mark"><Sparkles size={16} /></span>
					<span>PaperFlow <em className="brand-ai">AI</em></span>
				</button>
				<button className="icon-button sidebar-close" onClick={onClose} aria-label="Close navigation" type="button">
					<X size={18} />
				</button>
			</div>

			<button className="new-chat" onClick={() => onNavigate('chat')} type="button">
				<span>+</span> New chat
			</button>

			<nav className="main-nav" aria-label="Main navigation">
				{navItems.map(({ id, label, icon: Icon }) => (
					<button key={id} className={activeRoute === id ? 'active' : ''} onClick={() => onNavigate(id)} type="button">
						<Icon size={18} />
						{label}
					</button>
				))}
			</nav>

			<div className="sidebar-history">
				<div className="sidebar-section-label">Recent chats</div>
				{['Visa documents for Japan', 'Find my insurance details', 'Passport expiry details', 'Apartment checklist'].map((chat) => (
					<button key={chat} onClick={() => onNavigate('chat')} type="button">
						<span className="history-bullet">{chat === 'Visa documents for Japan' ? '✦' : '·'}</span>
						{chat}
					</button>
				))}
			</div>

			<div className="sidebar-section">
				<p className="eyebrow">Your library</p>
				<button onClick={() => onNavigate('documents')} type="button">
					<FolderOpen size={18} /> All documents <span className="nav-count">12</span>
				</button>
				<button onClick={() => onNavigate('connectors')} type="button">
					<Link2 size={18} /> Connected sources
				</button>
			</div>

			<div className="sidebar-bottom">
				<button onClick={() => onNavigate('settings')} className={activeRoute === 'settings' ? 'active' : ''} type="button">
					<Settings size={18} /> Settings
				</button>
				<div className="sidebar-note">
					<div className="note-icon"><Sparkles size={16} /></div>
					<div>
						<strong>Find more, faster</strong>
						<span>PaperFlow sees the whole picture.</span>
					</div>
				</div>
			</div>
		</aside>
	)
}
