import { useEffect, useState, useCallback, useRef } from 'react'
import { ArrowLeft, MoreHorizontal, Plus, MessageSquare, Trash2 } from 'lucide-react'
import ChatHistory from '../components/ChatHistory'
import ChatMessage from '../components/ChatMessage'
import PromptBar from '../components/PromptBar'
import LoadingMessage from '../components/LoadingMessage'
import { useAuth } from '../context/AuthContext'
import { chatApi } from '../services/api'

const ACTIVE_CHAT_KEY = 'paperflow_active_chat_id'

export default function Chat({ onNavigate }) {
	const { getToken, user } = useAuth()

	const [conversations, setConversations] = useState([])
	const [activeId, setActiveId] = useState(() => {
		return sessionStorage.getItem(ACTIVE_CHAT_KEY) || null
	})
	const [activeConversation, setActiveConversation] = useState(null)
	const [messages, setMessages] = useState([])
	const [loadingHistory, setLoadingHistory] = useState(true)
	const [loadingMessages, setLoadingMessages] = useState(false)
	const [sending, setSending] = useState(false)
	const [error, setError] = useState('')

	// ── 1. Fetch Conversations on Mount ───────────────────────────────────────

	const loadConversations = useCallback(async (selectId = null) => {
		const token = getToken()
		if (!token) return

		setLoadingHistory(true)
		setError('')
		try {
			const list = await chatApi.listConversations(token)
			setConversations(list || [])

			// Determine which conversation to select
			let targetId = selectId || activeId
			if (!targetId && list && list.length > 0) {
				targetId = list[0].id
			}

			if (targetId && list.some((c) => c.id === targetId)) {
				setActiveId(targetId)
				sessionStorage.setItem(ACTIVE_CHAT_KEY, targetId)
			} else if (list.length > 0) {
				setActiveId(list[0].id)
				sessionStorage.setItem(ACTIVE_CHAT_KEY, list[0].id)
			} else {
				setActiveId(null)
				sessionStorage.removeItem(ACTIVE_CHAT_KEY)
				setActiveConversation(null)
				setMessages([])
			}
		} catch (err) {
			setError('Could not load chat history.')
		} finally {
			setLoadingHistory(false)
		}
	}, [getToken, activeId])

	useEffect(() => {
		loadConversations()
	}, [loadConversations])

	// ── 2. Load Messages for Active Conversation ──────────────────────────────

	const loadActiveConversation = useCallback(async (convId) => {
		if (!convId) {
			setActiveConversation(null)
			setMessages([])
			return
		}

		const token = getToken()
		if (!token) return

		setLoadingMessages(true)
		setError('')
		try {
			const detail = await chatApi.getConversation(convId, token)
			setActiveConversation(detail)
			// Map messages to format expected by ChatMessage component
			const mapped = (detail.messages || []).map((m) => ({
				id: m.id,
				role: m.role,
				text: m.content,
				source: Array.isArray(m.sources) && m.sources[0]?.title
					? m.sources[0].title
					: typeof m.sources === 'string'
					? m.sources
					: null,
				created_at: m.created_at,
			}))
			setMessages(mapped)
		} catch (err) {
			setError('Could not load conversation messages.')
		} finally {
			setLoadingMessages(false)
		}
	}, [getToken])

	useEffect(() => {
		if (activeId) {
			loadActiveConversation(activeId)
		}
	}, [activeId, loadActiveConversation])

	// ── 3. Select Conversation ────────────────────────────────────────────────

	const handleSelectConversation = (convId) => {
		if (convId === activeId) return
		setActiveId(convId)
		sessionStorage.setItem(ACTIVE_CHAT_KEY, convId)
	}

	// ── 4. New Chat ───────────────────────────────────────────────────────────

	const handleNewChat = async () => {
		const token = getToken()
		if (!token) return

		try {
			const newConv = await chatApi.createConversation({ title: 'New chat' }, token)
			setConversations((prev) => [newConv, ...prev])
			setActiveId(newConv.id)
			sessionStorage.setItem(ACTIVE_CHAT_KEY, newConv.id)
			setActiveConversation({ ...newConv, messages: [] })
			setMessages([])
		} catch (err) {
			setError('Could not create new chat.')
		}
	}

	// ── 5. Delete Conversation ────────────────────────────────────────────────

	const handleDeleteConversation = async (convId) => {
		const token = getToken()
		if (!token) return

		try {
			await chatApi.deleteConversation(convId, token)
			setConversations((prev) => prev.filter((c) => c.id !== convId))
			if (activeId === convId) {
				const remaining = conversations.filter((c) => c.id !== convId)
				if (remaining.length > 0) {
					setActiveId(remaining[0].id)
					sessionStorage.setItem(ACTIVE_CHAT_KEY, remaining[0].id)
				} else {
					setActiveId(null)
					sessionStorage.removeItem(ACTIVE_CHAT_KEY)
					setActiveConversation(null)
					setMessages([])
				}
			}
		} catch (err) {
			setError('Could not delete conversation.')
		}
	}

	// ── 6. Send Message ───────────────────────────────────────────────────────

	const handleSend = async ({ text, file }) => {
		const queryText = text || (file ? `Review ${file.name}` : '')
		if (!queryText.trim()) return

		const token = getToken()
		if (!token) return

		setSending(true)
		setError('')

		try {
			let currentConvId = activeId

			// If no active conversation, create one first
			if (!currentConvId) {
				const created = await chatApi.createConversation({ title: 'New chat' }, token)
				currentConvId = created.id
				setActiveId(currentConvId)
				sessionStorage.setItem(ACTIVE_CHAT_KEY, currentConvId)
				setConversations((prev) => [created, ...prev])
			}

			// Save user message to database
			const savedMsg = await chatApi.sendMessage(
				currentConvId,
				{ content: queryText, role: 'user' },
				token
			)

			// Append message to UI
			const formattedUserMsg = {
				id: savedMsg.id,
				role: 'user',
				text: savedMsg.content,
				created_at: savedMsg.created_at,
			}
			setMessages((prev) => [...prev, formattedUserMsg])

			// Refresh conversation metadata (to reflect updated title and updated_at)
			const updatedList = await chatApi.listConversations(token)
			setConversations(updatedList || [])
			const updatedDetail = updatedList.find((c) => c.id === currentConvId)
			if (updatedDetail) {
				setActiveConversation((prev) => ({
					...prev,
					title: updatedDetail.title,
					updated_at: updatedDetail.updated_at,
				}))
			}
		} catch (err) {
			setError('Could not send message. Please try again.')
		} finally {
			setSending(false)
		}
	}

	const displayTitle = activeConversation?.title || 'New chat'

	return (
		<div className="chat-layout">
			<ChatHistory
				conversations={conversations}
				activeId={activeId}
				onSelect={handleSelectConversation}
				onNewChat={handleNewChat}
				onDelete={handleDeleteConversation}
				loading={loadingHistory}
			/>

			<section className="chat-panel">
				<div className="chat-header">
					<button className="back-link" onClick={() => onNavigate('home')}>
						<ArrowLeft size={16} /> Back home
					</button>

					<div>
						<strong>{displayTitle}</strong>
						<span>
							{messages.length} {messages.length === 1 ? 'message' : 'messages'}
						</span>
					</div>

					<div style={{ display: 'flex', gap: '6px', justifyContent: 'flex-end' }}>
						{activeId && (
							<button
								className="icon-button"
								onClick={() => handleDeleteConversation(activeId)}
								aria-label="Delete chat"
								title="Delete this conversation"
							>
								<Trash2 size={16} />
							</button>
						)}
					</div>
				</div>

				<div className="message-scroll">
					{error && (
						<p className="form-error" style={{ textAlign: 'center', margin: '10px 0' }}>
							{error}
						</p>
					)}

					{loadingMessages ? (
						<LoadingMessage />
					) : messages.length === 0 ? (
						<div
							style={{
								display: 'flex',
								flexDirection: 'column',
								alignItems: 'center',
								justifyContent: 'center',
								height: '100%',
								color: '#8c928a',
								textAlign: 'center',
								padding: '40px 20px',
							}}
						>
							<div
								style={{
									width: '48px',
									height: '48px',
									borderRadius: '12px',
									background: 'rgba(255,255,255,0.8)',
									display: 'grid',
									placeItems: 'center',
									marginBottom: '16px',
									boxShadow: 'var(--shadow)',
								}}
							>
								<MessageSquare size={22} color="var(--ink)" />
							</div>
							<h3 style={{ fontSize: '18px', fontWeight: 600, color: 'var(--ink)', margin: '0 0 8px' }}>
								{displayTitle === 'New chat' ? 'Start a new conversation' : displayTitle}
							</h3>
							<p style={{ fontSize: '13px', maxWidth: '340px', lineHeight: 1.5, margin: 0 }}>
								Ask a question about your documents, notes, or messages to get started.
							</p>
						</div>
					) : (
						messages.map((message, index) => (
							<ChatMessage key={message.id || index} message={message} />
						))
					)}

					{sending && <LoadingMessage />}
				</div>

				<div className="chat-composer">
					<PromptBar onSubmit={handleSend} loading={sending} />
					<span>PaperFlow can make mistakes. Check important details in the original source.</span>
				</div>
			</section>

			<button
				id="floating-new-chat-btn"
				className="floating-new"
				onClick={handleNewChat}
			>
				<Plus size={17} /> New chat
			</button>
		</div>
	)
}
