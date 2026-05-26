import type {
  CreateProjectPayload,
  FileTreeNode,
  PaginatedResult,
  ProjectItem,
  ProjectQuery,
} from '@/types'
import { requestData } from './http'

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
  object_key: string
  filename: string
  size_bytes: number
  file_count: number
  accepted_source_files: number
}

interface TaskStartOut {
  task_id: number
  status: string
  progress: number
}

function toProjectStatus(status: string): ProjectItem['status'] {
  if (status === 'created') return 'idle'
  if (status === 'parsing') return 'parsing'
  if (status === 'ready') return 'ready'
  if (status === 'failed') return 'error'
  return 'idle'
}

function toProjectItem(item: BackendProject): ProjectItem {
  return {
    id: String(item.id),
    name: item.name,
    description: `已扫描文件：${item.file_count}`,
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

export async function createProjectApi(payload: CreateProjectPayload): Promise<ProjectItem> {
  let zipObjectKey: string | null = null

  if (payload.sourceType === 'zip') {
    if (!payload.zipFile) {
      throw new Error('请选择 ZIP 文件')
    }

    const upload = await uploadZipFile(payload.zipFile)
    zipObjectKey = upload.object_key
  }

  const data = await requestData<BackendProjectCreateOut>({
    url: '/api/projects',
    method: 'post',
    data: {
      name: payload.name,
      language: 'Python',
      source_type: payload.sourceType,
      repo_url: payload.repoUrl || null,
      branch: null,
      zip_object_key: zipObjectKey,
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
    data: {
      mode: 'sync',
    },
  })
}

export async function syncProjectApi(projectId: string): Promise<TaskStartOut> {
  return requestData<TaskStartOut>({
    url: `/api/projects/${projectId}/sync`,
    method: 'post',
    data: {},
  })
}

export async function fetchProjectTreeApi(projectId: string): Promise<FileTreeNode[]> {
  return requestData<FileTreeNode[]>({
    url: `/api/projects/${projectId}/tree`,
    method: 'get',
  })
}