import { Bot, UserRound } from 'lucide-react'
import SourceBadge from './SourceBadge'

function formatMarkdownText(text = '') {
	const escaped = String(text)
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')

	return escaped
		.replace(/\n\n/g, '</p><p>')
		.replace(/\n/g, '<br />')
		.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
		.replace(/`([^`]+)`/g, '<code>$1</code>')
		.replace(/^- (.+)/gm, '<li>$1</li>')
		.replace(/<li>(.+)<\/li>/g, '<ul><li>$1</li></ul>')
		.replace(/<p>(<ul>.*?<\/ul>)<\/p>/g, '$1')
		.replace(/<p>\s*<\/p>/g, '')
		.replace(/^/, '<p>')
		.replace(/$/, '</p>')
}

export default function ChatMessage({ message }) {
	const isUser = message.role === 'user'
	const text = formatMarkdownText(message.text || '')

	return (
		<div className={`message-row ${isUser ? 'user-message' : 'assistant-message'}`}>
			<div className="message-avatar">{isUser ? <UserRound size={16} /> : <Bot size={17} />}</div>
			<div className="message-content">
				<span className="message-author">{isUser ? 'You' : 'PaperFlow AI'}</span>
				<div className="message-bubble" dangerouslySetInnerHTML={{ __html: text }} />
				{message.source && <SourceBadge source={message.source} />}
			</div>
		</div>
	)
}
