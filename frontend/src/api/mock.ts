import type { AxiosAdapter, AxiosRequestConfig, AxiosResponse, InternalAxiosRequestConfig } from 'axios'
import type {
  AdminOverview,
  AdminUserItem,
  ApiResponse,
  AuthSession,
  CreateProjectPayload,
  DiagramDetail,
  DiagramType,
  ExportResult,
  FileTreeNode,
  GenerateDiagramPayload,
  LoginPayload,
  PaginatedResult,
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
    id: 'user_demo',
    username: '演示用户',
    email: 'user@demo',
    password: 'user123',
    role: 'user',
    lastActiveAt: new Date().toISOString(),
  },
  {
    id: 'admin_demo',
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

const now = () => new Date().toISOString()
const uid = (prefix: string) => `${prefix}_${Math.random().toString(36).slice(2, 10)}`

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
    id: 'proj_demo_1',
    name: 'AI 仓库流程平台 Demo',
    description: '用于展示仓库解析、Mermaid 图表生成与源码追踪的演示项目。',
    sourceType: 'git',
    repoUrl: 'https://example.com/demo/repo.git',
    status: 'ready',
    diagramCount: 1,
    createdAt: now(),
    updatedAt: now(),
  }

  projects.push(project)
  projectOwners.set(project.id, 'user_demo')
  projectTrees.set(project.id, buildFileTree())
  projectDiagrams.set(project.id, {
    id: 'diagram_demo_1',
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
  const auth = (config.headers as Record<string, string> | undefined)?.Authorization ?? ''
  const token = auth.replace('Bearer ', '')
  const userId = token.replace('mock-token-', '')
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

function simulateTask(projectId: string, type: MockTaskType, onDone: () => void): void {
  const taskId = uid('task')
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

async function handleAuth(config: AxiosRequestConfig): Promise<AxiosResponse<ApiResponse<AuthSession>>> {
  if (config.url === '/api/auth/login') {
    const payload = parseBody<LoginPayload>(config)
    const match = users.find((user) => user.email === payload.email && user.password === payload.password)
    if (!match) {
      return createResponse<AuthSession>({ token: '', user: null as never }, '账号或密码错误', 401, 200)
    }

    match.lastActiveAt = now()
    return createResponse({
      token: `mock-token-${match.id}`,
      user: { id: match.id, username: match.username, email: match.email, role: match.role },
    })
  }

  const payload = parseBody<RegisterPayload>(config)
  const exists = users.some((user) => user.email === payload.email)
  if (exists) {
    return createResponse<AuthSession>({ token: '', user: null as never }, '该邮箱已注册', 409, 200)
  }

  const newUser = {
    id: uid('user'),
    username: payload.username,
    email: payload.email,
    password: payload.password,
    role: 'user' as const,
    lastActiveAt: now(),
  }
  users.push(newUser)

  return createResponse({
    token: `mock-token-${newUser.id}`,
    user: { id: newUser.id, username: newUser.username, email: newUser.email, role: newUser.role },
  }, '注册成功')
}

async function handleProjects(config: AxiosRequestConfig): Promise<AxiosResponse<ApiResponse<any>>> {
  const user = getCurrentUser(config)
  const method = config.method?.toLowerCase()
  const projectId = config.url?.match(/\/api\/projects\/([^/]+)/)?.[1]

  if (method === 'get' && config.url === '/api/projects') {
    const query = (config.params ?? { page: 1, pageSize: 8 }) as ProjectQuery
    const source = filterProjectsByUser(user)
    const keyword = query.keyword?.trim().toLowerCase() ?? ''
    const filtered = keyword
      ? source.filter((item) => `${item.name}${item.description}`.toLowerCase().includes(keyword))
      : source
    const page = Number(query.page || 1)
    const pageSize = Number(query.pageSize || 8)
    const start = (page - 1) * pageSize

    return createResponse<PaginatedResult<ProjectItem>>({
      list: filtered.slice(start, start + pageSize),
      pagination: {
        page,
        pageSize,
        total: filtered.length,
      },
    })
  }

  if (method === 'post' && config.url === '/api/projects') {
    const payload = parseBody<CreateProjectPayload>(config)
    const project: ProjectItem = {
      id: uid('proj'),
      name: payload.name,
      description: payload.description,
      sourceType: payload.sourceType,
      repoUrl: payload.repoUrl,
      status: 'idle',
      diagramCount: 0,
      createdAt: now(),
      updatedAt: now(),
    }
    projects.unshift(project)
    projectOwners.set(project.id, user?.id ?? 'user_demo')
    projectTrees.set(project.id, buildFileTree())
    projectDiagrams.set(project.id, {
      id: uid('diagram'),
      projectId: project.id,
      type: 'flowchart',
      version: 1,
      outdated: false,
      updatedAt: now(),
      ...buildMermaid('flowchart', payload.name, '初始化流程'),
    })
    return createResponse(project, '项目创建成功')
  }

  if (method === 'put' && projectId && !config.url?.includes('/diagram/')) {
    const payload = parseBody<Partial<ProjectItem>>(config)
    const project = getProjectById(projectId)
    Object.assign(project, payload, { updatedAt: now() })
    return createResponse(project, '项目更新成功')
  }

  if (method === 'delete' && projectId) {
    const index = projects.findIndex((item) => item.id === projectId)
    if (index >= 0) {
      projects.splice(index, 1)
      projectOwners.delete(projectId)
      projectTrees.delete(projectId)
      projectDiagrams.delete(projectId)
    }
    return createResponse(true, '项目已删除')
  }

  if (method === 'get' && config.url?.endsWith('/tree') && projectId) {
    return createResponse(projectTrees.get(projectId) ?? [])
  }

  if (method === 'post' && config.url?.endsWith('/parse') && projectId) {
    const project = getProjectById(projectId)
    project.status = 'parsing'
    project.updatedAt = now()
    simulateTask(projectId, 'parse', () => {
      project.status = 'ready'
      project.updatedAt = now()
    })
    return createResponse(true, '已开始解析仓库')
  }

  if (method === 'post' && config.url?.endsWith('/sync') && projectId) {
    const project = getProjectById(projectId)
    simulateTask(projectId, 'sync', () => {
      project.status = 'outdated'
      project.updatedAt = now()
      const diagram = projectDiagrams.get(projectId)
      if (diagram) {
        diagram.outdated = true
        diagram.updatedAt = now()
      }
    })
    return createResponse(true, '代码同步任务已启动')
  }

  if (method === 'post' && config.url?.endsWith('/upload-zip') && projectId) {
    const project = getProjectById(projectId)
    project.status = 'idle'
    project.updatedAt = now()
    return createResponse(true, 'ZIP 上传成功，等待解析')
  }

  throw new Error('未找到项目接口')
}

async function handleDiagram(config: AxiosRequestConfig): Promise<AxiosResponse<ApiResponse<any>>> {
  const method = config.method?.toLowerCase()
  const projectId = config.url?.match(/\/api\/projects\/([^/]+)/)?.[1]
  if (!projectId) throw new Error('缺少项目 ID')

  if (method === 'post' && config.url?.endsWith('/diagram/generate')) {
    const project = getProjectById(projectId)
    const payload = parseBody<GenerateDiagramPayload>(config)
    const current = projectDiagrams.get(projectId)

    simulateTask(projectId, 'diagram', () => {
      const built = buildMermaid(payload.type, project.name, payload.instruction)
      projectDiagrams.set(projectId, {
        id: current?.id ?? uid('diagram'),
        projectId,
        type: payload.type,
        version: (current?.version ?? 0) + 1,
        outdated: false,
        updatedAt: now(),
        shareUrl: current?.shareUrl,
        ...built,
      })
      project.diagramCount = 1
      project.status = 'ready'
      project.updatedAt = now()
    })
    return createResponse(true, '图表生成任务已提交')
  }

  if (method === 'get' && config.url?.endsWith('/diagram')) {
    return createResponse(projectDiagrams.get(projectId))
  }

  if (method === 'put' && config.url?.includes('/diagram/')) {
    const payload = parseBody<Partial<DiagramDetail>>(config)
    const diagram = projectDiagrams.get(projectId)
    if (!diagram) throw new Error('图表不存在')
    diagram.mermaidCode = payload.mermaidCode ?? diagram.mermaidCode
    diagram.type = payload.type ?? diagram.type
    diagram.outdated = false
    diagram.version += 1
    diagram.updatedAt = now()
    return createResponse(diagram, '图表保存成功')
  }

  if (method === 'post' && config.url?.endsWith('/export')) {
    const diagram = projectDiagrams.get(projectId)
    const payload = parseBody<{ type: 'svg' | 'png' | 'pdf' | 'markdown' }>(config)
    const result: ExportResult = {
      fileName: `${diagram?.title ?? 'diagram'}.${payload.type === 'markdown' ? 'md' : payload.type}`,
      mimeType: payload.type === 'markdown' ? 'text/markdown' : 'text/plain',
      content: payload.type === 'markdown' ? `\`\`\`mermaid\n${diagram?.mermaidCode ?? ''}\n\`\`\`` : diagram?.mermaidCode ?? '',
    }
    return createResponse(result)
  }

  if (method === 'post' && config.url?.endsWith('/share')) {
    const diagram = projectDiagrams.get(projectId)
    if (!diagram) throw new Error('图表不存在')
    diagram.shareUrl = `https://share.demo.ai/${diagram.id}`
    return createResponse({ shareUrl: diagram.shareUrl }, '分享链接已生成')
  }

  throw new Error('未找到图表接口')
}

async function handleAdmin(config: AxiosRequestConfig): Promise<AxiosResponse<ApiResponse<any>>> {
  const overview: AdminOverview = {
    userCount: users.length,
    projectCount: projects.length,
    taskCount: tasks.length,
    successRate: tasks.length ? Math.round((tasks.filter((item) => item.status === 'success').length / tasks.length) * 100) : 100,
    activeUsers: Math.max(1, users.length - 1),
  }

  if (config.url === '/api/admin/overview') {
    return createResponse(overview)
  }

  if (config.url === '/api/admin/users') {
    const result: AdminUserItem[] = users.map((user) => ({
      id: user.id,
      username: user.username,
      email: user.email,
      role: user.role,
      lastActiveAt: user.lastActiveAt,
      projectCount: projects.filter((project) => projectOwners.get(project.id) === user.id).length,
    }))
    return createResponse(result)
  }

  if (config.url === '/api/admin/tasks') {
    return createResponse(tasks)
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
    if (config.url?.includes('/diagram')) {
      return await handleDiagram(config)
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
