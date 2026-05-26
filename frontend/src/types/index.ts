export type UserRole = 'user' | 'admin'
export type ProjectSourceType = 'git' | 'zip'
export type ProjectStatus = 'idle' | 'parsing' | 'ready' | 'outdated' | 'error'
export type DiagramType = 'flowchart' | 'sequenceDiagram' | 'stateDiagram' | 'classDiagram'
export type TaskStatus = 'pending' | 'running' | 'success' | 'error'
export type SocketStatus = 'idle' | 'connecting' | 'connected' | 'disconnected' | 'error'
export type ExportType = 'svg' | 'png' | 'pdf' | 'markdown'

export interface ApiResponse<T> {
  code: number
  message: string
  data: T
  success?: boolean
  trace_id?: string
}

export interface UserProfile {
  id: string
  username: string
  email: string
  role: UserRole
}

export interface AuthSession {
  token: string
  user: UserProfile
}

export interface LoginPayload {
  email: string
  password: string
}

export interface RegisterPayload {
  username: string
  email: string
  password: string
}

export interface Pagination {
  page: number
  pageSize: number
  total: number
}

export interface PaginatedResult<T> {
  list: T[]
  pagination: Pagination
}

export interface ProjectItem {
  id: string
  name: string
  description: string
  sourceType: ProjectSourceType
  repoUrl?: string
  status: ProjectStatus
  diagramCount: number
  updatedAt: string
  createdAt: string
}

export interface ProjectQuery {
  page: number
  pageSize: number
  keyword?: string
}

export interface CreateProjectPayload {
  name: string
  description: string
  sourceType: ProjectSourceType
  repoUrl?: string
  zipFileName?: string
  zipFile?: File | null
}

export interface FileTreeNode {
  id: string
  name: string
  path: string
  type: 'directory' | 'file'
  children?: FileTreeNode[]
}

export interface DiagramNodeSource {
  filePath: string
  startLine: number
  endLine: number
  code: string
}

export interface DiagramDetail {
  id: string
  projectId: string
  title: string
  type: DiagramType
  mermaidCode: string
  version: number
  outdated: boolean
  updatedAt: string
  sourceMap: Record<string, DiagramNodeSource>
  shareUrl?: string
}

export interface GenerateDiagramPayload {
  instruction: string
  type: DiagramType
  selectedPaths: string[]
}

export interface TaskProgressEvent {
  projectId: string
  taskId: string
  type: 'parse' | 'sync' | 'diagram'
  progress: number
  status: TaskStatus
  message: string
  updatedAt: string
}

export interface ExportResult {
  fileName: string
  mimeType: string
  content: string
}

export interface AdminOverview {
  userCount: number
  projectCount: number
  taskCount: number
  successRate: number
  activeUsers: number
}

export interface AdminUserItem extends UserProfile {
  lastActiveAt: string
  projectCount: number
}
