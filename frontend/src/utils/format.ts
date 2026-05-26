import type { ProjectStatus, UserRole } from '@/types'

const statusLabelMap: Record<ProjectStatus, string> = {
  idle: '待处理',
  parsing: '解析中',
  ready: '已就绪',
  outdated: '图表过期',
  error: '异常',
}

const roleLabelMap: Record<UserRole, string> = {
  user: '普通用户',
  admin: '管理员',
}

export function formatDateTime(value?: string): string {
  if (!value) return '--'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

export function getProjectStatusLabel(status: ProjectStatus): string {
  return statusLabelMap[status]
}

export function getRoleLabel(role: UserRole): string {
  return roleLabelMap[role]
}

export function toPercent(value: number): string {
  return `${Math.min(100, Math.max(0, value))}%`
}
