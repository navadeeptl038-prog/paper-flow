import { createContext, useContext, useEffect, useState } from 'react'

const AuthContext = createContext(null)

const defaultUser = { username: 'Aarav', email: 'aarav@example.com', initials: 'AR' }

export function AuthProvider({ children }) {
	const [user, setUser] = useState(() => {
		try { return JSON.parse(localStorage.getItem('paperflow-user')) || null } catch { return null }
	})

	useEffect(() => {
		if (user) localStorage.setItem('paperflow-user', JSON.stringify(user))
		else localStorage.removeItem('paperflow-user')
	}, [user])

	const login = ({ email }) => setUser({ ...defaultUser, email, username: email.split('@')[0] || defaultUser.username })
	const signup = ({ username, email }) => setUser({ ...defaultUser, username: username || defaultUser.username, email, initials: (username || 'AR').slice(0, 2).toUpperCase() })
	const logout = () => setUser(null)

	return <AuthContext.Provider value={{ user, login, signup, logout }}>{children}</AuthContext.Provider>
}

export function useAuth() { return useContext(AuthContext) }
