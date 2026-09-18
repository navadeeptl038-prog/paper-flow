import { useEffect, useState } from 'react'
import { AuthProvider, useAuth } from './context/AuthContext'
import Navbar from './components/Navbar'
import Sidebar from './components/Sidebar'
import Home from './pages/Home'
import Chat from './pages/Chat'
import Documents from './pages/Documents'
import Connectors from './pages/Connectors'
import Settings from './pages/Settings'
import Login from './pages/Login'
import Signup from './pages/Signup'
import VerifyEmail from './pages/VerifyEmail'

const routes = { home: Home, chat: Chat, documents: Documents, connectors: Connectors, settings: Settings }

function Workspace() {
	const { user } = useAuth()
	const [route, setRoute] = useState(window.location.hash.replace('#/', '') || 'home')
	const [sidebarOpen, setSidebarOpen] = useState(false)

	useEffect(() => {
		const onHashChange = () => setRoute(window.location.hash.replace('#/', '') || 'home')
		window.addEventListener('hashchange', onHashChange)
		return () => window.removeEventListener('hashchange', onHashChange)
	}, [])

	const navigate = (nextRoute) => {
		window.location.hash = `/${nextRoute}`
		setSidebarOpen(false)
	}

	if (!user) {
		if (route === 'signup') return <Signup onNavigate={navigate} />
		if (route === 'verify') return <VerifyEmail onNavigate={navigate} />
		return <Login onNavigate={navigate} />
	}

	const Page = routes[route] || Home
	return (
		<div className={`app-shell ${route === 'home' ? 'home-shell' : ''}`}>
			<Sidebar activeRoute={route} onNavigate={navigate} open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
			<div className="app-main">
				<Navbar home={route === 'home'} onMenu={() => setSidebarOpen(true)} onNavigate={navigate} />
				<main className="page-wrap"><Page onNavigate={navigate} /></main>
			</div>
		</div>
	)
}

export default function App() {
	return <AuthProvider><Workspace /></AuthProvider>
}
