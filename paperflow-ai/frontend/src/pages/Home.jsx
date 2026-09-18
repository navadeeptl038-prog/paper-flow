import { useState } from 'react'
import PromptBar from '../components/PromptBar'
import WelcomeMessage from '../components/WelcomeMessage'
import ExampleCards from '../components/ExampleCards'
import LoadingMessage from '../components/LoadingMessage'
import { FileText, FolderOpen, Image, Table2 } from 'lucide-react'
import { healthCheck } from '../services/api'

export default function Home({ onNavigate }) {
	const [query, setQuery] = useState('')
	const [loading, setLoading] = useState(false)
	const [healthState, setHealthState] = useState({ status: 'idle', message: '' })
	const ask = ({ text }) => { setQuery(text); setLoading(true); setTimeout(() => { setLoading(false); onNavigate('chat') }, 900) }
	const checkBackend = async () => { setHealthState({ status: 'loading', message: 'Checking backend...' }); try { const result = await healthCheck(); setHealthState({ status: 'success', message: `Backend connected: ${result.status}` }) } catch (error) { setHealthState({ status: 'error', message: error.message }) } }
	return <div className="home-page"><div className="home-decorations" aria-hidden="true"><span className="decor-tile decor-pdf"><FileText size={25} /></span><span className="decor-tile decor-doc"><FileText size={24} /></span><span className="decor-tile decor-image"><Image size={24} /></span><span className="decor-tile decor-sheet"><Table2 size={24} /></span><span className="decor-tile decor-folder"><FolderOpen size={24} /></span></div><div className="home-intro"><WelcomeMessage /><div className="prompt-stage"><PromptBar onSubmit={ask} loading={loading} /><span className="prompt-caption">Private by design. Your sources stay yours.</span></div>{loading && <LoadingMessage />}</div><div className="example-section"><div className="section-heading"><span>Start with a question</span><span className="section-rule" /></div><ExampleCards onSelect={(text) => { setQuery(text); ask({ text }) }} /></div><div className="backend-check"><button className="button quiet" onClick={checkBackend} disabled={healthState.status === 'loading'}>{healthState.status === 'loading' ? 'Checking...' : 'Check backend'}</button>{healthState.message && <span className={`health-message ${healthState.status}`}>{healthState.message}</span>}</div><div className="home-footer"><span>PaperFlow AI</span><span>Search less. Live more.</span></div></div>
}
