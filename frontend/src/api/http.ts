import axios, { AxiosHeaders } from 'axios'
import type { ApiResponse } from '@/types'
import { getStoredToken } from '@/utils/storage'
import { mockAdapter } from './mock'

const enableMock = import.meta.env.VITE_ENABLE_MOCK === 'true'

export const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 12000,
  adapter: enableMock ? mockAdapter : undefined,
})

http.interceptors.request.use((config) => {
  const token = getStoredToken()
  config.headers = config.headers ?? new AxiosHeaders()

  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }

  return config
})

http.interceptors.response.use(
  (response) => response,
  (error) => {
    const message = error?.response?.data?.message || error.message || '网络请求失败'
    return Promise.reject(new Error(message))
  },
)

export async function requestData<T>(
  config: Parameters<typeof http.request<ApiResponse<T>>>[0],
): Promise<T> {
  const response = await http.request<ApiResponse<T>>(config)

  const ok = response.data.code === 0 || response.data.success === true

  if (!ok) {
    throw new Error(response.data.message || '接口调用失败')
  }

  return response.data.data
}