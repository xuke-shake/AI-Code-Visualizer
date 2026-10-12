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

function toBackendUser(data: BackendUser): UserProfile {
  if (!data || data.id == null || !data.email) throw new Error('会话响应缺少用户信息')
  return toUserProfile(data)
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
  const token = typeof data?.access_token === 'string' ? data.access_token.trim() : ''
  if (!token || token === 'undefined' || token === 'null') {
    throw new Error('登录响应缺少有效 access_token')
  }
  if (!data?.user) {
    throw new Error('登录响应缺少用户信息')
  }
  return {
    token,
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

export async function fetchCurrentUserApi(): Promise<UserProfile> {
  const data = await requestData<BackendUser>({
    url: '/api/auth/me',
    method: 'get',
  })
  return toBackendUser(data)
}
