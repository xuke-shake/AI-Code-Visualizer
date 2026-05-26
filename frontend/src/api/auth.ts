import type { AuthSession, LoginPayload, RegisterPayload, UserProfile } from '@/types'
import { requestData } from './http'

interface BackendUser {
  id: number
  email: string
  nickname?: string | null
  role: 'user' | 'admin'
  status: string
  created_at: string
  last_login_at?: string | null
}

interface BackendAuthSession {
  access_token: string
  token_type: string
  user: BackendUser
}

function toUserProfile(user: BackendUser): UserProfile {
  return {
    id: String(user.id),
    username: user.nickname || user.email.split('@')[0],
    email: user.email,
    role: user.role,
  }
}

function toAuthSession(data: BackendAuthSession): AuthSession {
  return {
    token: data.access_token,
    user: toUserProfile(data.user),
  }
}

export async function loginApi(payload: LoginPayload): Promise<AuthSession> {
  const data = await requestData<BackendAuthSession>({
    url: '/api/auth/login',
    method: 'post',
    data: payload,
  })

  return toAuthSession(data)
}

export async function registerApi(payload: RegisterPayload): Promise<AuthSession> {
  const data = await requestData<BackendAuthSession>({
    url: '/api/auth/register',
    method: 'post',
    data: {
      email: payload.email,
      password: payload.password,
      nickname: payload.username,
    },
  })

  return toAuthSession(data)
}