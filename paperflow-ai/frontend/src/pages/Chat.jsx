import { useState } from 'react'
import { ArrowLeft, MoreHorizontal, Plus } from 'lucide-react'
import ChatHistory from '../components/ChatHistory'
import ChatMessage from '../components/ChatMessage'
import PromptBar from '../components/PromptBar'
import LoadingMessage from '../components/LoadingMessage'

const starter = [{ role: 'user', text: 'What documents do I need for a visa?' }, { role: 'assistant', text: 'I found a few useful pieces across your sources. For a visa application, you currently have your passport and bank statement ready. You may still need proof of accommodation and a recent photograph.', source: 'Local Storage' }]

export default function Chat({ onNavigate }) {
	const [messages, setMessages] = useState(starter)
	const [loading, setLoading] = useState(false)
	const send = ({ text, file }) => { const next = text || `Review ${file?.name}`; setMessages((current) => [...current, { role: 'user', text: next }]); setLoading(true); setTimeout(() => { setMessages((current) => [...current, { role: 'assistant', text: 'I am searching your connected sources for the best match. This is a local preview of the conversation experience.', source: 'Google Drive' }]); setLoading(false) }, 800) }
	return <div className="chat-layout"><ChatHistory /><section className="chat-panel"><div className="chat-header"><button className="back-link" onClick={() => onNavigate('home')}><ArrowLeft size={16} /> Back home</button><div><strong>Visa documents for Japan</strong><span>Conversation · 2 sources</span></div><button className="icon-button" aria-label="Conversation options"><MoreHorizontal size={20} /></button></div><div className="message-scroll">{messages.map((message, index) => <ChatMessage key={index} message={message} />)}{loading && <LoadingMessage />}</div><div className="chat-composer"><PromptBar onSubmit={send} loading={loading} /><span>PaperFlow can make mistakes. Check important details in the original source.</span></div></section><button className="floating-new" onClick={() => setMessages([])}><Plus size={17} /> New chat</button></div>
}
