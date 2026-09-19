import { LogOut } from 'lucide-react'
import { useAuth } from '../context/AuthContext'

export default function UserMenu() {
	const { logout } = useAuth()

	return (
		<button className="user-menu" onClick={logout} aria-label="Log out" title="Log out" type="button">
			<LogOut size={17} />
		</button>
	)
}
