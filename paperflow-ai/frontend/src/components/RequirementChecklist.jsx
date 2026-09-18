import { Check, Circle } from 'lucide-react'

export default function RequirementChecklist({ items = [] }) {
	return <div className="requirement-list">{items.map((item) => <div className={`requirement-item ${item.present ? 'present' : 'missing'}`} key={item.label}>{item.present ? <span className="check-icon"><Check size={13} /></span> : <Circle size={18} strokeWidth={1.5} />}<div><strong>{item.label}</strong><span>{item.present ? item.file : 'Not found in your connected sources'}</span></div><em>{item.present ? 'Present' : 'Missing'}</em></div>)}</div>
}
