import { LogOut, UserRound } from 'lucide-react'
import { useAuth } from '../context/AuthContext'

export default function UserMenu() {
	const { user, logout } = useAuth()
	return <div className="user-menu"><div className="avatar">{user?.initials || 'AR'}</div><div className="user-copy"><strong>{user?.username || 'Aarav'}</strong><span>Personal workspace</span></div><button className="icon-button" onClick={logout} aria-label="Log out" title="Log out"><LogOut size={17} /></button></div>
}
