import type { AxiosAdapter, AxiosRequestConfig, AxiosResponse, InternalAxiosRequestConfig } from 'axios'
import type {
  ApiResponse,
  CreateProjectPayload,
  DiagramDetail,
  DiagramType,
  FileTreeNode,
  GenerateDiagramPayload,
  LoginPayload,
  ProjectItem,
  ProjectQuery,
  RegisterPayload,
  TaskProgressEvent,
  UserProfile,
} from '@/types'

type MockTaskType = 'parse' | 'sync' | 'diagram'
type TaskListener = (payload: TaskProgressEvent) => void

const listeners = new Set<TaskListener>()
const users: Array<UserProfile & { password: string; lastActiveAt: string }> = [
  {
    id: '1',
    username: '演示用户',
    email: 'user@demo',
    password: 'user123',
    role: 'user',
    lastActiveAt: new Date().toISOString(),
  },
  {
    id: '2',
    username: '平台管理员',
    email: 'admin@demo',
    password: 'admin123',
    role: 'admin',
    lastActiveAt: new Date().toISOString(),
  },
]

const projects: ProjectItem[] = []
const tasks: TaskProgressEvent[] = []
const projectOwners = new Map<string, string>()
const projectTrees = new Map<string, FileTreeNode[]>()
const projectDiagrams = new Map<string, DiagramDetail>()
const uploads = new Map<number, { filename: string; sizeBytes: number }>()
let nextEntityId = 100

const now = () => new Date().toISOString()
const uid = (prefix: string) => `${prefix}_${Math.random().toString(36).slice(2, 10)}`
const entityId = () => String(nextEntityId++)
const backendId = (value: string): number => Number(value)

function buildFileTree(): FileTreeNode[] {
  return [
    {
      id: uid('dir'),
      name: 'src',
      path: 'src',
      type: 'directory',
      children: [
        {
          id: uid('dir'),
          name: 'api',
          path: 'src/api',
          type: 'directory',
          children: [
            { id: uid('file'), name: 'project.ts', path: 'src/api/project.ts', type: 'file' },
            { id: uid('file'), name: 'diagram.ts', path: 'src/api/diagram.ts', type: 'file' },
          ],
        },
        {
          id: uid('dir'),
          name: 'stores',
          path: 'src/stores',
          type: 'directory',
          children: [
            { id: uid('file'), name: 'projectStore.ts', path: 'src/stores/projectStore.ts', type: 'file' },
            { id: uid('file'), name: 'diagramStore.ts', path: 'src/stores/diagramStore.ts', type: 'file' },
          ],
        },
        { id: uid('file'), name: 'App.vue', path: 'src/App.vue', type: 'file' },
      ],
    },
    {
      id: uid('dir'),
      name: 'server',
      path: 'server',
      type: 'directory',
      children: [
        { id: uid('file'), name: 'workflow.service.ts', path: 'server/workflow.service.ts', type: 'file' },
      ],
    },
    { id: uid('file'), name: 'README.md', path: 'README.md', type: 'file' },
  ]
}

function buildSourceMap(projectName: string, type: DiagramType): DiagramDetail['sourceMap'] {
  if (type === 'sequenceDiagram') {
    return {
      用户: {
        filePath: 'src/views/LoginView.vue',
        startLine: 1,
        endLine: 12,
        code: `<script setup lang="ts">\n// ${projectName} 登录请求由用户发起\nconst submit = async () => {\n  // 触发登录\n}\n</script>`,
      },
      前端工作台: {
        filePath: 'src/views/WorkspaceView.vue',
        startLine: 16,
        endLine: 38,
        code: `<script setup lang="ts">\n// 工作台负责收集指令并请求图表生成\nconst handleGenerate = async () => {\n  await diagramStore.generateDiagram()\n}\n</script>`,
      },
      后端服务: {
        filePath: 'server/workflow.service.ts',
        startLine: 8,
        endLine: 32,
        code: `export async function parseRepository() {\n  // 调度仓库解析、业务识别与图表生成\n  return true\n}`,
      },
      AI解析器: {
        filePath: 'server/ai-parser.ts',
        startLine: 4,
        endLine: 24,
        code: `export async function buildMermaidByPrompt(prompt: string) {\n  // 根据用户指令生成 Mermaid 图表\n  return 'sequenceDiagram'\n}`,
      },
    }
  }

  if (type === 'classDiagram') {
    return {
      ProjectStore: {
        filePath: 'src/stores/projectStore.ts',
        startLine: 1,
        endLine: 28,
        code: `export const useProjectStore = defineStore('project', {\n  // 管理项目列表、当前项目与解析状态\n})`,
      },
      DiagramStore: {
        filePath: 'src/stores/diagramStore.ts',
        startLine: 1,
        endLine: 30,
        code: `export const useDiagramStore = defineStore('diagram', {\n  // 管理图表内容、编辑与导出分享\n})`,
      },
      MermaidCanvas: {
        filePath: 'src/components/MermaidCanvas.vue',
        startLine: 1,
        endLine: 30,
        code: `<script setup lang="ts">\n// 负责渲染、缩放、重绘以及节点点击事件\n</script>`,
      },
    }
  }

  return {
    登录入口: {
      filePath: 'src/views/LoginView.vue',
      startLine: 18,
      endLine: 38,
      code: `<script setup lang="ts">\n// 登录成功后进入项目列表或管理员后台\nconst submit = async () => {\n  await userStore.login(form)\n}\n</script>`,
    },
    项目列表: {
      filePath: 'src/views/ProjectListView.vue',
      startLine: 24,
      endLine: 48,
      code: `<script setup lang="ts">\n// 项目列表页负责搜索、分页、新建项目\nconst openCreateDialog = () => {\n  visible.value = true\n}\n</script>`,
    },
    仓库解析: {
      filePath: 'server/workflow.service.ts',
      startLine: 6,
      endLine: 24,
      code: `export async function parseRepositoryJob(projectId: string) {\n  // 解析仓库结构并生成节点映射\n  return { projectId }\n}`,
    },
    Mermaid画布: {
      filePath: 'src/components/MermaidCanvas.vue',
      startLine: 1,
      endLine: 40,
      code: `<script setup lang="ts">\n// Mermaid 画布根据文本实时重绘\nwatch(() => props.code, renderDiagram)\n</script>`,
    },
    源码面板: {
      filePath: 'src/components/SourcePanel.vue',
      startLine: 1,
      endLine: 30,
      code: `<script setup lang="ts">\n// 根据节点展示只读源码和高亮行\n</script>`,
    },
    导出分享: {
      filePath: 'src/components/ExportDialog.vue',
      startLine: 1,
      endLine: 24,
      code: `<script setup lang="ts">\n// 支持导出 SVG、PNG、PDF 和 Markdown\n</script>`,
    },
  }
}

function buildMermaid(type: DiagramType, projectName: string, instruction: string): Pick<DiagramDetail, 'title' | 'mermaidCode' | 'sourceMap'> {
  if (type === 'sequenceDiagram') {
    return {
      title: `${projectName} 时序视图`,
      mermaidCode: `sequenceDiagram
    participant 用户
    participant 前端工作台
    participant 后端服务
    participant AI解析器
    用户->>前端工作台: 输入指令 ${instruction || '生成业务流程图'}
    前端工作台->>后端服务: 请求生成图表
    后端服务->>AI解析器: 解析仓库与业务流
    AI解析器-->>后端服务: 返回 Mermaid 结果
    后端服务-->>前端工作台: 推送图表数据
    前端工作台-->>用户: 展示图表与源码定位`,
      sourceMap: buildSourceMap(projectName, type),
    }
  }

  if (type === 'stateDiagram') {
    return {
      title: `${projectName} 状态视图`,
      mermaidCode: `stateDiagram-v2
    [*] --> 空闲
    空闲 --> 解析中: 开始解析
    解析中 --> 就绪: 解析完成
    解析中 --> 错误: 解析失败
    就绪 --> 过期: 代码同步
    过期 --> 解析中: 重新解析
    就绪 --> [*]: 完成
    错误 --> 空闲: 重试`,
      sourceMap: buildSourceMap(projectName, type),
    }
  }

  if (type === 'classDiagram') {
    return {
      title: `${projectName} 架构类图`,
      mermaidCode: `classDiagram
    class ProjectStore {
      +fetchProjects()
      +createProject()
      +syncProject()
    }
    class DiagramStore {
      +generateDiagram()
      +saveDiagram()
      +shareDiagram()
    }
    class MermaidCanvas {
      +render()
      +zoomIn()
      +zoomOut()
    }
    ProjectStore --> DiagramStore
    DiagramStore --> MermaidCanvas`,
      sourceMap: buildSourceMap(projectName, type),
    }
  }

  return {
    title: `${projectName} 流程总览`,
    mermaidCode: `flowchart LR
    A["登录入口"] --> B["项目列表"]
    B --> C["仓库解析"]
    C --> D["Mermaid画布"]
    D --> E["源码面板"]
    D --> F["导出分享"]
    B --> G["管理员后台"]`,
    sourceMap: buildSourceMap(projectName, type),
  }
}

function seedData(): void {
  if (projects.length) return

  const project: ProjectItem = {
    id: '10',
    name: 'AI 仓库流程平台 Demo',
    fileCount: 0,
    sourceType: 'git',
    repoUrl: 'https://example.com/demo/repo.git',
    status: 'ready',
    diagramCount: 1,
    createdAt: now(),
    updatedAt: now(),
  }

  projects.push(project)
  projectOwners.set(project.id, '1')
  projectTrees.set(project.id, buildFileTree())
  projectDiagrams.set(project.id, {
    id: '20',
    projectId: project.id,
    type: 'flowchart',
    version: 1,
    outdated: false,
    updatedAt: now(),
    ...buildMermaid('flowchart', project.name, '演示流程'),
  })
}

function emitTask(payload: TaskProgressEvent): void {
  tasks.unshift(payload)
  listeners.forEach((listener) => listener(payload))
}

function createResponse<T>(data: T, message = '请求成功', code = 0, status = 200): AxiosResponse<ApiResponse<T>> {
  return {
    config: {} as InternalAxiosRequestConfig,
    data: { code, message, data, success: code === 0 },
    headers: {},
    status,
    statusText: 'OK',
  }
}

function parseBody<T>(config: AxiosRequestConfig): T {
  if (!config.data) return {} as T
  return typeof config.data === 'string' ? (JSON.parse(config.data) as T) : (config.data as T)
}

function getCurrentUser(config: AxiosRequestConfig): UserProfile | null {
  const headers = config.headers as Record<string, string> | undefined
  const auth = headers?.Authorization ?? headers?.authorization ?? ''
  const token = auth.replace(/^Bearer\s+/i, '').trim()
  if (!token || token === 'undefined' || token === 'null' || !token.startsWith('mock-token-')) return null
  const userId = token.slice('mock-token-'.length)
  const match = users.find((item) => item.id === userId)

  return match
    ? {
        id: match.id,
        username: match.username,
        email: match.email,
        role: match.role,
      }
    : null
}

function simulateTask(projectId: string, type: MockTaskType, onDone: () => void): string {
  const taskId = entityId()
  const steps = [
    { progress: 10, message: '开始处理任务' },
    { progress: 35, message: '解析仓库结构与业务节点' },
    { progress: 68, message: '生成节点映射与关联源码' },
    { progress: 92, message: '整理最终结果' },
    { progress: 100, message: '任务执行完成' },
  ]

  steps.forEach((step, index) => {
    setTimeout(() => {
      emitTask({
        projectId,
        taskId,
        type,
        progress: step.progress,
        status: step.progress === 100 ? 'success' : 'running',
        message: step.message,
        updatedAt: now(),
      })

      if (step.progress === 100) {
        onDone()
      }
    }, 520 * (index + 1))
  })
  return taskId
}

function filterProjectsByUser(user: UserProfile | null): ProjectItem[] {
  if (!user) return []
  if (user.role === 'admin') return projects
  return projects.filter((project) => projectOwners.get(project.id) === user.id)
}

function getProjectById(projectId: string): ProjectItem {
  const project = projects.find((item) => item.id === projectId)
  if (!project) {
    throw new Error('项目不存在')
  }
  return project
}

function toBackendProject(project: ProjectItem): Record<string, unknown> {
  return {
    id: backendId(project.id),
    owner_id: backendId(projectOwners.get(project.id) ?? '1'),
    name: project.name,
    language: 'Python',
    source_type: project.sourceType,
    status: project.status === 'idle' ? 'created' : project.status === 'error' ? 'failed' : project.status,
    file_count: projectTrees.get(project.id)?.length ?? 0,
    last_index_version: null,
    config_json: null,
    created_at: project.createdAt,
    updated_at: project.updatedAt,
  }
}

function toBackendDiagram(diagram: DiagramDetail): Record<string, unknown> {
  return {
    id: backendId(diagram.id),
    project_id: backendId(diagram.projectId),
    creator_id: 1,
    title: diagram.title,
    diagram_type: diagram.type === 'sequenceDiagram' ? 'sequence' : diagram.type === 'stateDiagram' ? 'state' : diagram.type === 'classDiagram' ? 'architecture' : 'flowchart',
    prompt: null,
    mermaid_code: diagram.mermaidCode,
    node_mapping_json: Object.fromEntries(Object.entries(diagram.sourceMap).map(([key, value]) => [key, {
      file_path: value.filePath,
      start_line: value.startLine,
      end_line: value.endLine,
      code: value.code,
    }])),
    version: diagram.version,
    is_outdated: diagram.outdated,
    created_at: diagram.updatedAt,
  }
}

async function handleAuth(config: AxiosRequestConfig): Promise<AxiosResponse<ApiResponse<any>>> {
  if (config.url === '/api/auth/me') {
    const currentUser = getCurrentUser(config)
    if (!currentUser) return createResponse(null, '未登录或Token无效', 401, 401)
    const stored = users.find((item) => item.id === currentUser.id)
    return createResponse({
      id: backendId(currentUser.id),
      email: currentUser.email,
      nickname: currentUser.username,
      role: currentUser.role,
      status: 'normal',
      created_at: stored?.lastActiveAt ?? now(),
      last_login_at: stored?.lastActiveAt ?? null,
    })
  }
  const isLogin = config.url === '/api/auth/login'
  const payload = parseBody<LoginPayload & RegisterPayload>(config)
  const normalizedEmail = String(payload.email || '').trim().toLowerCase()
  const match = isLogin
    ? users.find((user) => user.email.trim().toLowerCase() === normalizedEmail && user.password === payload.password)
    : undefined

  if (isLogin && !match) return createResponse(null, '账号或密码错误', 401, 401)
  if (!isLogin && users.some((user) => user.email.trim().toLowerCase() === normalizedEmail)) {
    return createResponse(null, '该邮箱已注册', 409, 409)
  }

  const user = match ?? {
    id: entityId(),
    username: payload.username ?? (payload as { nickname?: string }).nickname ?? '',
    email: normalizedEmail,
    password: payload.password,
    role: 'user' as const,
    lastActiveAt: now(),
  }
  if (!match) users.push(user)
  user.lastActiveAt = now()

  return createResponse({
    access_token: `mock-token-${user.id}`,
    token_type: 'bearer',
    user: {
      id: backendId(user.id),
      email: user.email,
      nickname: user.username,
      role: user.role,
      status: 'active',
      created_at: user.lastActiveAt,
      last_login_at: user.lastActiveAt,
    },
  }, isLogin ? '登录成功' : '注册成功')
}

async function handleProjects(config: AxiosRequestConfig): Promise<AxiosResponse<ApiResponse<any>>> {
  const user = getCurrentUser(config)
  const method = config.method?.toLowerCase()
  const projectId = config.url?.match(/\/api\/projects\/([^/]+)/)?.[1]

  if (method === 'get' && config.url === '/api/projects') {
    const query = (config.params ?? { page: 1, page_size: 10 }) as ProjectQuery & { page_size?: number }
    const source = filterProjectsByUser(user)
    const keyword = query.keyword?.trim().toLowerCase() ?? ''
    const filtered = keyword
      ? source.filter((item) => item.name.toLowerCase().includes(keyword))
      : source
    const page = Number(query.page || 1)
    const pageSize = Number(query.page_size || query.pageSize || 10)
    const start = (page - 1) * pageSize

    return createResponse({
      items: filtered.slice(start, start + pageSize).map(toBackendProject),
      total: filtered.length,
      page,
      page_size: pageSize,
    })
  }

  if (method === 'post' && config.url === '/api/projects') {
    const payload = parseBody<Record<string, any> & CreateProjectPayload>(config)
    const sourceType = (payload.source_type ?? payload.sourceType) as 'git' | 'zip'
    if (sourceType === 'zip' && (payload.repo_url || !payload.upload_id)) throw new Error('ZIP项目必须只提供上传文件')
    if (sourceType === 'git' && (payload.upload_id || !payload.repo_url)) throw new Error('Git项目必须只提供仓库地址')
    const project: ProjectItem = {
      id: entityId(),
      name: payload.name,
      fileCount: 0,
      sourceType,
    repoUrl: payload.repo_url ?? payload.repoUrl,
      status: 'idle',
      diagramCount: 0,
      createdAt: now(),
      updatedAt: now(),
    }
    projects.unshift(project)
    projectOwners.set(project.id, user?.id ?? '1')
    projectTrees.set(project.id, buildFileTree())
    projectDiagrams.set(project.id, {
      id: entityId(),
      projectId: project.id,
      type: 'flowchart',
      version: 1,
      outdated: false,
      updatedAt: now(),
      ...buildMermaid('flowchart', payload.name, '初始化流程'),
    })
    return createResponse({ project: toBackendProject(project), task_id: null }, '项目创建成功')
  }

  if (method === 'get' && projectId && config.url === `/api/projects/${projectId}`) {
    return createResponse(toBackendProject(getProjectById(projectId)))
  }

  if (method === 'patch' && projectId) {
    const payload = parseBody<Record<string, any>>(config)
    const project = getProjectById(projectId)
    if (payload.name !== undefined) project.name = payload.name
    if (payload.source_type !== undefined) project.sourceType = payload.source_type
    Object.assign(project, { updatedAt: now() })
    return createResponse(toBackendProject(project), '项目更新成功')
  }

  if (method === 'delete' && projectId) {
    const index = projects.findIndex((item) => item.id === projectId)
    if (index >= 0) {
      projects.splice(index, 1)
      projectOwners.delete(projectId)
      projectTrees.delete(projectId)
      projectDiagrams.delete(projectId)
    }
    return createResponse({ deleted: true }, '项目已删除')
  }

  if (method === 'get' && config.url?.endsWith('/tree') && projectId) {
    return createResponse(projectTrees.get(projectId) ?? [])
  }

  if (method === 'post' && config.url?.endsWith('/parse') && projectId) {
    const project = getProjectById(projectId)
    project.status = 'parsing'
    project.updatedAt = now()
    const taskId = simulateTask(projectId, 'parse', () => {
      project.status = 'ready'
      project.updatedAt = now()
    })
    return createResponse({ task_id: Number(taskId), status: 'running', progress: 10 }, '已开始解析仓库')
  }

  if (method === 'post' && config.url?.endsWith('/sync') && projectId) {
    const project = getProjectById(projectId)
    const taskId = simulateTask(projectId, 'sync', () => {
      project.status = 'outdated'
      project.updatedAt = now()
      const diagram = projectDiagrams.get(projectId)
      if (diagram) {
        diagram.outdated = true
        diagram.updatedAt = now()
      }
    })
    return createResponse({ task_id: Number(taskId), status: 'running', progress: 10 }, '代码同步任务已启动')
  }

  if (method === 'post' && config.url === '/api/uploads') {
    const file = config.data instanceof FormData ? config.data.get('file') : null
    const uploadId = nextEntityId++
    const filename = file instanceof File ? file.name : 'upload.zip'
    const sizeBytes = file instanceof File ? file.size : 0
    uploads.set(uploadId, { filename, sizeBytes })
    return createResponse({
      upload_id: uploadId,
      filename,
      size_bytes: sizeBytes,
      file_count: 1,
      accepted_source_files: 1,
      validation_status: 'validated',
      created_at: now(),
    }, '上传成功')
  }

  throw new Error('未找到项目接口')
}

async function handleDiagram(config: AxiosRequestConfig): Promise<AxiosResponse<ApiResponse<any>>> {
  const method = config.method?.toLowerCase()
  const projectId = config.url?.match(/\/api\/projects\/([^/]+)/)?.[1]
  const diagramId = config.url?.match(/\/api\/diagrams\/([^/]+)/)?.[1]

  if (method === 'post' && config.url?.match(/\/api\/projects\/[^/]+\/analysis$/)) {
    if (!projectId) throw new Error('缺少项目 ID')
    const project = getProjectById(projectId)
    const body = parseBody<Record<string, any>>(config)
    const payload: GenerateDiagramPayload = {
      instruction: body.prompt ?? '',
      type: body.diagram_type === 'sequence' ? 'sequenceDiagram' : body.diagram_type === 'state' ? 'stateDiagram' : body.diagram_type === 'architecture' ? 'classDiagram' : 'flowchart',
      selectedPaths: body.parameters?.selectedPaths ?? [],
    }
    let taskId = ''
    await new Promise<void>((resolve) => {
      taskId = simulateTask(projectId, 'diagram', () => {
      const built = buildMermaid(payload.type, project.name, payload.instruction)
      projectDiagrams.set(projectId, {
        id: entityId(),
        projectId,
        type: payload.type,
        version: 1,
        outdated: false,
        updatedAt: now(),
        ...built,
      })
      project.diagramCount = 1
      project.status = 'ready'
      project.updatedAt = now()
      resolve()
      })
    })
    const diagram = projectDiagrams.get(projectId)
    return createResponse({ task_id: Number(taskId), status: 'success', diagram_id: diagram ? Number(diagram.id.replace(/\D/g, '')) || 1 : null }, '图表生成成功')
  }

  if (method === 'get' && diagramId) {
    const diagram = [...projectDiagrams.values()].find((item) => item.id === diagramId || item.id.replace(/\D/g, '') === diagramId)
    if (!diagram) throw new Error('图表不存在')
    return createResponse(toBackendDiagram(diagram))
  }

  if (method === 'get' && config.url?.endsWith('/diagram') && projectId) {
    const diagram = projectDiagrams.get(projectId)
    return createResponse(diagram ? toBackendDiagram(diagram) : null)
  }

  if (method === 'patch' && diagramId) {
    const payload = parseBody<Record<string, any>>(config)
    const diagram = [...projectDiagrams.values()].find((item) => item.id === diagramId || item.id.replace(/\D/g, '') === diagramId)
    if (!diagram) throw new Error('图表不存在')
    diagram.mermaidCode = payload.mermaid_code ?? diagram.mermaidCode
    diagram.title = payload.title ?? diagram.title
    diagram.outdated = false
    diagram.version += 1
    diagram.updatedAt = now()
    return createResponse(toBackendDiagram(diagram), '图表保存成功')
  }

  if (method === 'post' && diagramId && config.url?.endsWith('/export')) {
    const diagram = [...projectDiagrams.values()].find((item) => item.id === diagramId || item.id.replace(/\D/g, '') === diagramId)
    const payload = parseBody<{ format: 'svg' | 'png' | 'pdf' | 'markdown' }>(config)
    return createResponse({ download_url: '', object_key: `${diagram?.title ?? 'diagram'}.${payload.format === 'markdown' ? 'md' : payload.format}`, format: payload.format })
  }

  if (method === 'post' && diagramId && config.url?.endsWith('/share')) {
    const diagram = [...projectDiagrams.values()].find((item) => item.id === diagramId || item.id.replace(/\D/g, '') === diagramId)
    if (!diagram) throw new Error('图表不存在')
    diagram.shareUrl = `/share/${uid('share')}`
    return createResponse({ share_url: diagram.shareUrl, share_token: uid('token'), expires_at: now() }, '分享链接已生成')
  }

  throw new Error('未找到图表接口')
}

async function handleAdmin(config: AxiosRequestConfig): Promise<AxiosResponse<ApiResponse<any>>> {
  if (config.url === '/api/admin/metrics') {
    const failed = tasks.filter((item) => item.status === 'error').length
    const success = tasks.filter((item) => item.status === 'success').length
    return createResponse({
      user_count: users.length,
      project_count: projects.length,
      task_count: tasks.length,
      failed_task_count: failed,
      success_rate: tasks.length ? success / tasks.length : 0,
      diagram_count: projectDiagrams.size,
      token_usage: null,
    })
  }

  if (config.url === '/api/admin/users') {
    return createResponse({ items: users.map((user) => ({
      user: { id: Number(user.id), email: user.email, nickname: user.username, role: user.role, status: 'active', created_at: user.lastActiveAt, last_login_at: user.lastActiveAt },
      quota: null,
    })), total: users.length, page: 1, page_size: users.length || 1 })
  }

  if (config.url === '/api/admin/tasks') {
    return createResponse({ items: tasks.map((task) => ({ id: Number(task.taskId), project_id: Number(task.projectId), user_id: 1, task_type: task.type, status: task.status === 'error' ? 'failed' : task.status, progress: task.progress, message: task.message, result_json: null, created_at: task.updatedAt, finished_at: task.status === 'success' ? task.updatedAt : null })), total: tasks.length, page: 1, page_size: tasks.length || 1 })
  }

  throw new Error('未找到管理员接口')
}

seedData()

export const mockAdapter: AxiosAdapter = async (config) => {
  await new Promise((resolve) => setTimeout(resolve, 280))

  try {
    if (config.url?.startsWith('/api/auth/')) {
      return await handleAuth(config)
    }
    if (config.url?.includes('/analysis') || config.url?.includes('/diagram')) {
      return await handleDiagram(config)
    }
    if (config.url?.startsWith('/api/uploads')) {
      return await handleProjects(config)
    }
    if (config.url?.startsWith('/api/projects')) {
      return await handleProjects(config)
    }
    if (config.url?.startsWith('/api/admin')) {
      return await handleAdmin(config)
    }
    return createResponse(null, '未找到接口', 404, 200)
  } catch (error) {
    return createResponse(null, error instanceof Error ? error.message : '请求失败', 500, 200)
  }
}

export function createTaskStream(projectId: string, onMessage: TaskListener, onStatus?: (status: string) => void): () => void {
  onStatus?.('connected')
  const listener = (payload: TaskProgressEvent) => {
    if (payload.projectId === projectId) {
      onMessage(payload)
    }
  }
  listeners.add(listener)

  return () => {
    listeners.delete(listener)
    onStatus?.('disconnected')
  }
}
