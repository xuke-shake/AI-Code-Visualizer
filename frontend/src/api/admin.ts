import type { AdminOverview, AdminUserItem, TaskProgressEvent } from '@/types'
import { requestData } from './http'

export function fetchAdminOverviewApi(): Promise<AdminOverview> {
  return requestData({ url: '/api/admin/overview', method: 'get' })
}

export function fetchAdminUsersApi(): Promise<AdminUserItem[]> {
  return requestData({ url: '/api/admin/users', method: 'get' })
}

export function fetchAdminTasksApi(): Promise<TaskProgressEvent[]> {
  return requestData({ url: '/api/admin/tasks', method: 'get' })
}
