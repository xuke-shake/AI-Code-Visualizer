import type { UserProfile } from '@/types'

const TOKEN_KEY = 'ai-flow-token'
const USER_KEY = 'ai-flow-user'

export function getStoredToken(): string {
  const token = localStorage.getItem(TOKEN_KEY)?.trim() ?? ''
  return token && token !== 'undefined' && token !== 'null' ? token : ''
}

export function setStoredToken(token: string): void {
  const normalized = typeof token === 'string' ? token.trim() : ''
  if (!normalized || normalized === 'undefined' || normalized === 'null') {
    clearStoredToken()
    return
  }
  localStorage.setItem(TOKEN_KEY, normalized)
}

export function clearStoredToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export function getStoredUser(): UserProfile | null {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as Partial<UserProfile>
    if (!parsed.id || !parsed.email || !parsed.role) return null
    return parsed as UserProfile
  } catch {
    clearStoredUser()
    return null
  }
}

export function setStoredUser(user: UserProfile): void {
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearStoredUser(): void {
  localStorage.removeItem(USER_KEY)
}
