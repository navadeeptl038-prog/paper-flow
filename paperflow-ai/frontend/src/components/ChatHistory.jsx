const conversations = ['Visa documents for Japan', 'Find my insurance details', 'What is my passport expiry?', 'Receipts from last summer', 'Apartment application checklist']

export default function ChatHistory({ onSelect }) {
	return <aside className="chat-history"><div className="section-heading"><span>Chat history</span><span className="history-count">{conversations.length}</span></div><div className="history-list">{conversations.map((item, index) => <button key={item} className={index === 0 ? 'selected' : ''} onClick={() => onSelect?.(item)}><span className="history-icon">{index === 0 ? '✦' : '·'}</span>{item}</button>)}</div></aside>
}
