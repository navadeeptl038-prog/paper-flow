import { Sparkles } from 'lucide-react'
import { useAuth } from '../context/AuthContext'

export default function WelcomeMessage() {
	const { user } = useAuth()
	return <section className="welcome-block"><div className="hero-logo"><span className="hero-mark"><Sparkles size={29} /></span></div><div className="hero-product">PaperFlow <em>AI</em></div><h1>{user?.username || 'Aarav'} returns<span className="accent-dot">!</span></h1><p>Everything you need is already within reach. Ask a question, find a file, or figure out what comes next.</p></section>
}
