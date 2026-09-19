import { Plus, Trash2 } from 'lucide-react'

export default function ChatHistory({
	conversations = [],
	activeId = null,
	onSelect,
	onNewChat,
	onDelete,
	loading = false,
}) {
	return (
		<aside className="chat-history" aria-label="Chat History">
			<div className="history-header">
				<div className="history-title-wrap">
					<span>Chat History</span>
					<span className="history-count">{conversations.length}</span>
				</div>
				<button id="new-chat-sidebar-btn" className="sidebar-new-chat" onClick={onNewChat} title="Start a new chat" type="button">
					<Plus size={12} /> New Chat
				</button>
			</div>

			<div className="history-list">
				{loading && <div className="history-empty">Loading history…</div>}

				{!loading && conversations.length === 0 && (
					<div className="history-empty">
						No chats yet. Click <strong>+ New Chat</strong> to start!
					</div>
				)}

				{!loading && conversations.map((item) => {
					const isSelected = item.id === activeId
					return (
						<div key={item.id} className={`history-item ${isSelected ? 'is-selected' : ''}`}>
							<button type="button" className={isSelected ? 'selected' : ''} onClick={() => onSelect?.(item.id)} title={item.title}>
								<span className="history-icon">{isSelected ? '✦' : '·'}</span>
								<span className="history-label">{item.title || 'New chat'}</span>
							</button>

							{onDelete && (
								<button
									type="button"
									className="history-delete"
									onClick={(e) => {
										e.stopPropagation()
										onDelete(item.id)
									}}
									title="Delete chat"
									aria-label={`Delete conversation ${item.title}`}
								>
									<Trash2 size={12} />
								</button>
							)}
						</div>
					)
				})}
			</div>
		</aside>
	)
}
