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
			<div className="section-heading" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
				<div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
					<span>Chat History</span>
					<span className="history-count">{conversations.length}</span>
				</div>
				<button
					id="new-chat-sidebar-btn"
					onClick={onNewChat}
					style={{
						background: 'transparent',
						border: '1px solid var(--line)',
						borderRadius: '6px',
						padding: '4px 8px',
						fontSize: '10px',
						fontWeight: 700,
						cursor: 'pointer',
						display: 'flex',
						alignItems: 'center',
						gap: '4px',
						color: 'var(--ink)'
					}}
					title="Start a new chat"
				>
					<Plus size={12} /> New Chat
				</button>
			</div>

			<div className="history-list">
				{loading && (
					<div style={{ padding: '14px 8px', fontSize: '11px', color: '#999d96' }}>
						Loading history…
					</div>
				)}

				{!loading && conversations.length === 0 && (
					<div style={{ padding: '14px 8px', fontSize: '11px', color: '#999d96' }}>
						No chats yet. Click <strong>+ New Chat</strong> to start!
					</div>
				)}

				{!loading && conversations.map((item) => {
					const isSelected = item.id === activeId
					return (
						<div
							key={item.id}
							style={{
								display: 'flex',
								alignItems: 'center',
								position: 'relative',
								borderRadius: '7px',
								overflow: 'hidden'
							}}
						>
							<button
								type="button"
								className={isSelected ? 'selected' : ''}
								onClick={() => onSelect?.(item.id)}
								title={item.title}
								style={{
									flex: 1,
									display: 'flex',
									alignItems: 'center',
									gap: '4px',
									width: '100%',
									paddingRight: onDelete ? '28px' : '8px'
								}}
							>
								<span className="history-icon">{isSelected ? '✦' : '·'}</span>
								<span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
									{item.title || 'New chat'}
								</span>
							</button>

							{onDelete && (
								<button
									type="button"
									onClick={(e) => {
										e.stopPropagation()
										onDelete(item.id)
									}}
									title="Delete chat"
									style={{
										position: 'absolute',
										right: '4px',
										background: 'transparent',
										border: 'none',
										padding: '4px',
										cursor: 'pointer',
										color: '#999d96',
										opacity: isSelected ? 0.9 : 0.4
									}}
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
