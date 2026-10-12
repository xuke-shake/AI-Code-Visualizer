import type { AdminOverview, AdminUserItem, TaskProgressEvent } from '@/types'
import { requestData } from './http'

interface BackendMetrics {
  user_count: number
  project_count: number
  task_count: number
  failed_task_count: number
  success_rate: number
  diagram_count: number
  token_usage: number | null
  usage_collected_calls?: number
  usage_unknown_calls?: number
}

interface BackendAdminUser {
  user: { id: number; email: string; nickname?: string | null; role: 'user' | 'admin'; last_login_at?: string | null }
  quota: unknown
}

interface BackendTask {
  id: number
  project_id: number
  task_type: string
  status: string
  progress: number
  message?: string | null
  created_at: string
  finished_at?: string | null
}

interface BackendPage<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export async function fetchAdminOverviewApi(): Promise<AdminOverview> {
  const data = await requestData<BackendMetrics>({ url: '/api/admin/metrics', method: 'get' })
  return {
    userCount: data.user_count,
    projectCount: data.project_count,
    taskCount: data.task_count,
    successRate: Math.round(data.success_rate * 100),
    // 后端未提供 activity window，不能把用户总数冒充活动用户数。
    activeUsers: 0,
    tokenUsage: data.token_usage,
    usageCollectedCalls: data.usage_collected_calls ?? 0,
    usageUnknownCalls: data.usage_unknown_calls ?? 0,
  }
}

export function formatTokenUsage(value: number | null | undefined): string {
  return typeof value === 'number' ? String(value) : '未统计'
}

export async function fetchAdminUsersApi(): Promise<AdminUserItem[]> {
  const data = await requestData<BackendPage<BackendAdminUser>>({ url: '/api/admin/users', method: 'get', params: { page: 1, page_size: 100 } })
  return data.items.map(({ user }) => ({
    id: String(user.id),
    username: user.nickname || user.email.split('@')[0],
    email: user.email,
    role: user.role,
    lastActiveAt: user.last_login_at || '',
    projectCount: null,
  }))
}

export async function fetchAdminTasksApi(): Promise<TaskProgressEvent[]> {
  const data = await requestData<BackendPage<BackendTask>>({ url: '/api/admin/tasks', method: 'get', params: { page: 1, page_size: 100 } })
  return data.items.map((task) => ({
    projectId: String(task.project_id),
    taskId: String(task.id),
    type: task.task_type === 'diagram' ? 'diagram' : task.task_type === 'sync' ? 'sync' : 'parse',
    progress: task.progress,
    status: task.status === 'failed' ? 'error' : task.status === 'success' ? 'success' : 'running',
    message: task.message || '',
    updatedAt: task.finished_at || task.created_at,
  }))
}
