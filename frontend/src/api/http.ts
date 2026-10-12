import axios, { AxiosHeaders } from 'axios'
import type { ApiResponse } from '@/types'
import { getStoredToken } from '@/utils/storage'
import { API_BASE_URL, ENABLE_MOCK, OPERATION_TIMEOUT_MS } from '@/utils/config'
import { mockAdapter } from './mock'

type AuthInvalidationHandler = () => void
let authInvalidationHandler: AuthInvalidationHandler | null = null

export function setAuthInvalidationHandler(handler: AuthInvalidationHandler | null): void {
  authInvalidationHandler = handler
}

function errorMessage(payload: unknown, fallback = '网络请求失败'): string {
  if (typeof payload === 'string' && payload.trim()) return payload.trim()
  if (payload && typeof payload === 'object') {
    const body = payload as { message?: unknown; detail?: unknown }
    for (const value of [body.message, body.detail]) {
      if (typeof value === 'string' && value.trim()) return value.trim()
      if (Array.isArray(value) && value.length) {
        const first = value[0] as { msg?: unknown } | unknown
        if (first && typeof first === 'object' && typeof (first as { msg?: unknown }).msg === 'string') {
          return (first as { msg: string }).msg
        }
        return '请求参数格式不正确'
      }
      if (value && typeof value === 'object' && typeof (value as { msg?: unknown }).msg === 'string') {
        return (value as { msg: string }).msg
      }
    }
  }
  return fallback
}

export const http = axios.create({
  baseURL: API_BASE_URL,
  timeout: OPERATION_TIMEOUT_MS,
  adapter: ENABLE_MOCK ? mockAdapter : undefined,
})

http.interceptors.request.use((config) => {
  const token = getStoredToken()
  ;(config as typeof config & { authTokenAtRequest?: string }).authTokenAtRequest = token
  config.headers = config.headers ?? new AxiosHeaders()

  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }

  return config
})

http.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error?.response?.status
    const requestToken = (error?.config as { authTokenAtRequest?: string } | undefined)?.authTokenAtRequest ?? ''
    if (status === 401 && requestToken === getStoredToken()) authInvalidationHandler?.()
    const message = errorMessage(error?.response?.data, error?.message || '网络请求失败')
    const normalized = new Error(message)
    ;(normalized as Error & { status?: number }).status = status
    const taskId = error?.response?.data?.data?.task_id
    if (Number.isSafeInteger(taskId) && taskId > 0) (normalized as Error & { taskId?: number }).taskId = taskId
    return Promise.reject(normalized)
  },
)

export async function requestData<T>(
  config: Parameters<typeof http.request<ApiResponse<T>>>[0],
): Promise<T> {
  const response = await http.request<ApiResponse<T>>(config)

  const body = response.data
  const ok = body?.code === 0 || body?.success === true

  if (!ok) {
    const requestToken = (response.config as { authTokenAtRequest?: string }).authTokenAtRequest ?? ''
    if ((body?.code === 401 || response.status === 401) && requestToken === getStoredToken()) authInvalidationHandler?.()
    throw new Error(errorMessage(body, '接口调用失败'))
  }

  return body.data
}
