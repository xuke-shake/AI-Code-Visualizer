import type {
  CreateProjectPayload,
  FileTreeNode,
  PaginatedResult,
  ProjectItem,
  ProjectQuery,
} from '@/types'
import { requestData } from './http'
import { OPERATION_TIMEOUT_MS } from '@/utils/config'

interface BackendPage<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

interface BackendProject {
  id: number
  owner_id: number
  name: string
  language?: string | null
  source_type: 'git' | 'zip'
  status: string
  file_count: number
  last_index_version?: string | null
  config_json?: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

interface BackendProjectCreateOut {
  project: BackendProject
  task_id: number | null
}

interface UploadOut {
  upload_id: number
  filename: string
  size_bytes: number
  file_count: number
  accepted_source_files: number
  validation_status: string
  created_at: string
}

interface TaskStartOut {
  task_id: number
  status: string
  progress: number
}

export interface BackendTaskSnapshot {
  result_json?: { diagnostics?: Array<{ relative_path: string; status: string; message: string }>; retained_old_index?: boolean } | null
  id: number
  project_id: number
  task_type: string
  status: string
  progress: number
  message?: string | null
  created_at: string
  finished_at?: string | null
}

function toProjectStatus(status: string): ProjectItem['status'] {
  if (status === 'created') return 'idle'
  if (['parsing', 'indexing', 'fetching', 'pending', 'running'].includes(status)) return 'parsing'
  if (status === 'ready') return 'ready'
  if (status === 'outdated') return 'outdated'
  if (status === 'failed') return 'error'
  return 'idle'
}

function toProjectItem(item: BackendProject): ProjectItem {
  return {
    id: String(item.id),
    name: item.name,
    fileCount: item.file_count,
    sourceType: item.source_type,
    status: toProjectStatus(item.status),
    diagramCount: 0,
    updatedAt: item.updated_at,
    createdAt: item.created_at,
  }
}

async function uploadZipFile(file: File): Promise<UploadOut> {
  const formData = new FormData()
  formData.append('file', file)

  return requestData<UploadOut>({
    url: '/api/uploads',
    method: 'post',
    timeout: OPERATION_TIMEOUT_MS,
    data: formData,
  })
}

export async function fetchProjectsApi(params: ProjectQuery): Promise<PaginatedResult<ProjectItem>> {
  const data = await requestData<BackendPage<BackendProject>>({
    url: '/api/projects',
    method: 'get',
    params: {
      page: params.page,
      page_size: params.pageSize,
      keyword: params.keyword || undefined,
    },
  })

  return {
    list: data.items.map(toProjectItem),
    pagination: {
      page: data.page,
      pageSize: data.page_size,
      total: data.total,
    },
  }
}

export async function fetchProjectApi(projectId: string): Promise<ProjectItem> {
  const data = await requestData<BackendProject>({
    url: `/api/projects/${projectId}`,
    method: 'get',
  })

  return toProjectItem(data)
}

export async function createProjectApi(payload: CreateProjectPayload): Promise<ProjectItem> {
  let uploadId: number | null = null

  const sourceType = payload.sourceType
  const name = payload.name.trim()
  if (!name) throw new Error('项目名称不能为空')
  if (name.length > 128) throw new Error('项目名称不能超过128个字符')
  const repoUrl = payload.repoUrl?.trim() ?? ''
  if (sourceType === 'git' && !repoUrl) throw new Error('请输入 GitHub 仓库地址')
  if (sourceType === 'zip' && !payload.zipFile) throw new Error('请选择 ZIP 文件')

  if (sourceType === 'zip') {

    const upload = await uploadZipFile(payload.zipFile)
    uploadId = upload.upload_id
  }

  const data = await requestData<BackendProjectCreateOut>({
    url: '/api/projects',
    method: 'post',
    timeout: OPERATION_TIMEOUT_MS,
    data: {
      name,
      language: 'Python',
      source_type: sourceType,
      ...(sourceType === 'git'
        ? { repo_url: repoUrl, branch: null, upload_id: null }
        : { repo_url: null, branch: null, upload_id: uploadId }),
    },
  })

  return toProjectItem(data.project)
}

export async function updateProjectApi(projectId: string, payload: Partial<ProjectItem>): Promise<ProjectItem> {
  const data = await requestData<BackendProject>({
    url: `/api/projects/${projectId}`,
    method: 'patch',
    data: {
      name: payload.name,
    },
  })

  return toProjectItem(data)
}

export async function deleteProjectApi(projectId: string): Promise<boolean> {
  await requestData<{ deleted: boolean }>({
    url: `/api/projects/${projectId}`,
    method: 'delete',
  })

  return true
}

export async function parseProjectApi(projectId: string): Promise<TaskStartOut> {
  return requestData<TaskStartOut>({
    url: `/api/projects/${projectId}/parse`,
    method: 'post',
    timeout: OPERATION_TIMEOUT_MS,
    data: {
      mode: 'sync',
    },
  })
}

export async function fetchTaskApi(taskId: string): Promise<BackendTaskSnapshot> {
  return requestData<BackendTaskSnapshot>({ url: `/api/tasks/${taskId}`, method: 'get' })
}

export async function syncProjectApi(projectId: string): Promise<TaskStartOut> {
  return requestData<TaskStartOut>({
    url: `/api/projects/${projectId}/sync`,
    method: 'post',
    timeout: OPERATION_TIMEOUT_MS,
    data: {},
  })
}

export async function fetchProjectTreeApi(projectId: string): Promise<FileTreeNode[]> {
  return requestData<FileTreeNode[]>({
    url: `/api/projects/${projectId}/tree`,
    method: 'get',
  })
}
