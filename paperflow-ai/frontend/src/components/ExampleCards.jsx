import { ArrowUpRight, FileSearch, ListChecks, Search } from 'lucide-react'

const examples = [
	{ label: 'Find information', text: 'Find my Aadhaar number', icon: Search, tone: 'coral' },
	{ label: 'Find a document', text: 'Find my ATM card', icon: FileSearch, tone: 'blue' },
	{ label: 'Check requirements', text: 'What documents do I need for a visa?', icon: ListChecks, tone: 'green' },
]

export default function ExampleCards({ onSelect }) {
	return <div className="example-grid">{examples.map(({ label, text, icon: Icon, tone }) => <button key={label} className={`example-card ${tone}`} onClick={() => onSelect?.(text)}><span className="example-icon"><Icon size={19} /></span><span className="example-copy"><small>{label}</small><strong>“{text}”</strong></span><ArrowUpRight size={17} className="example-arrow" /></button>)}</div>
}
