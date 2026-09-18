import { ArrowUp, Paperclip, X } from 'lucide-react'
import { useRef, useState } from 'react'

const accepted = '.pdf,.docx,.jpg,.jpeg,.png,.webp,.heic,.heif'

export default function PromptBar({ onSubmit, loading = false, disabled = false }) {
	const [value, setValue] = useState('')
	const [file, setFile] = useState(null)
	const [dragging, setDragging] = useState(false)
	const fileInput = useRef(null)
	const submit = () => { if ((value.trim() || file) && !loading && !disabled) { onSubmit?.({ text: value.trim(), file }); setValue(''); setFile(null) } }
	const chooseFile = (picked) => { if (picked) setFile(picked) }
	return <div className={`prompt-wrap ${dragging ? 'is-dragging' : ''} ${disabled ? 'is-disabled' : ''}`} onDragOver={(event) => { event.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); chooseFile(event.dataTransfer.files[0]) }}>
		{file && <div className="attachment-chip"><Paperclip size={14} /> {file.name}<button onClick={() => setFile(null)} aria-label="Remove attachment"><X size={14} /></button></div>}
		<textarea value={value} disabled={disabled} onChange={(event) => setValue(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit() } }} placeholder="Stop Searching. Start Finding." aria-label="Ask PaperFlow" rows="1" />
		<div className="prompt-tools"><span className="prompt-hint">{dragging ? 'Drop to attach' : 'Ask a question or drop a file here'}</span><div className="prompt-actions"><input ref={fileInput} type="file" accept={accepted} hidden onChange={(event) => chooseFile(event.target.files[0])} /><button className="icon-button" onClick={() => fileInput.current?.click()} disabled={disabled} aria-label="Attach a file"><Paperclip size={19} /></button><button className="send-button" onClick={submit} disabled={disabled || loading || (!value.trim() && !file)} aria-label="Send">{loading ? <span className="spinner" /> : <ArrowUp size={19} />}</button></div></div>
	</div>
}
