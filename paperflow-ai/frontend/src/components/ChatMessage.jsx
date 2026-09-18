import { Bot, UserRound } from 'lucide-react'
import SourceBadge from './SourceBadge'

export default function ChatMessage({ message }) {
	const isUser = message.role === 'user'
	return <div className={`message-row ${isUser ? 'user-message' : 'assistant-message'}`}><div className="message-avatar">{isUser ? <UserRound size={16} /> : <Bot size={17} />}</div><div className="message-content"><span className="message-author">{isUser ? 'You' : 'PaperFlow'}</span><p>{message.text}</p>{message.source && <SourceBadge source={message.source} />}</div></div>
}
