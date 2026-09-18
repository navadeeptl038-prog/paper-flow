export const authService = {
	login: ({ email }) => ({ email }),
	signup: ({ username, email }) => ({ username, email }),
	verifyEmail: () => ({ verified: true }),
}
