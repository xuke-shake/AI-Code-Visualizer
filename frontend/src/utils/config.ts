const env = import.meta.env

function normalizeOptionalUrl(value: unknown): string {
  return typeof value === 'string' ? value.trim().replace(/\/$/, '') : ''
}

/** 前端统一运行配置；API 路径本身包含 /api 前缀。 */
export const API_BASE_URL = normalizeOptionalUrl(env.VITE_API_BASE_URL)
export const DEV_BACKEND_URL = normalizeOptionalUrl(env.VITE_DEV_BACKEND_URL) || 'http://127.0.0.1:8000'
export const WS_BASE_URL = normalizeOptionalUrl(env.VITE_WS_BASE_URL) || 'ws://127.0.0.1:8000/ws'
export const ENABLE_MOCK = env.VITE_ENABLE_MOCK === 'true'

function operationTimeout(value: unknown): number {
  const parsed = Number(value ?? 180000)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 180000
}

export const OPERATION_TIMEOUT_MS = operationTimeout(env.VITE_OPERATION_TIMEOUT_MS)

