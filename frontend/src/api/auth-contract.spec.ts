import { beforeEach, describe, expect, it } from 'vitest'
import type { InternalAxiosRequestConfig } from 'axios'
import { mockAdapter } from './mock'
import { clearStoredToken, getStoredToken, setStoredToken } from '@/utils/storage'

describe('认证接口契约', () => {
  beforeEach(() => {
    clearStoredToken()
  })

  it('mock /api/auth/me 返回真实后端 UserOut 字段', async () => {
    const response = await mockAdapter({
      url: '/api/auth/me',
      method: 'get',
      headers: { Authorization: 'Bearer mock-token-1' },
    } as InternalAxiosRequestConfig)

    expect(response.status).toBe(200)
    expect(response.data.code).toBe(0)
    expect(response.data.data).toMatchObject({
      id: 1,
      email: 'user@demo',
      nickname: '演示用户',
      role: 'user',
      status: 'normal',
    })
  })

  it('mock /api/auth/me 拒绝空值、undefined 和未知 token', async () => {
    for (const authorization of ['', 'Bearer undefined', 'Bearer null', 'Bearer unknown']) {
      const response = await mockAdapter({
        url: '/api/auth/me',
        method: 'get',
        headers: { Authorization: authorization },
      } as InternalAxiosRequestConfig)
      expect(response.status).toBe(401)
      expect(response.data.code).toBe(401)
    }
  })

  it('存储层不会把 undefined 或 null 当作有效 token', () => {
    setStoredToken('undefined')
    expect(getStoredToken()).toBe('')
    setStoredToken('null')
    expect(getStoredToken()).toBe('')
    setStoredToken('  valid-token  ')
    expect(getStoredToken()).toBe('valid-token')
  })
})
