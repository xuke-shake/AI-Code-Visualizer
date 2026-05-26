# AI仓库流程可视化平台 - 后端接口文档

## 一、接口规范

### 1.1 基础信息
- **协议**：HTTP/HTTPS
- **数据格式**：JSON
- **字符编码**：UTF-8
- **请求头**：`Content-Type: application/json`
- **认证方式**：JWT Token（除登录/注册外）

### 1.2 统一响应格式
```json
{
  "code": 200,
  "message": "success",
  "data": {},
  "trace_id": "uuid"
}
```

### 1.3 状态码
| 状态码 | 含义 |
|--------|------|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 401 | 未认证/Token过期 |
| 403 | 无权限 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

---

## 二、认证接口

### 2.1 用户注册
- **接口**：`POST /api/auth/register`
- **权限**：公开
- **请求参数**：
```json
{
  "username": "string",  // 用户名，必填，2-20字符
  "email": "string",     // 邮箱，必填，有效邮箱格式
  "password": "string"   // 密码，必填，6-20字符
}
```
- **响应数据**：
```json
{
  "token": "string",
  "user": {
    "id": "string",
    "username": "string",
    "email": "string",
    "role": "user"
  }
}
```

### 2.2 用户登录
- **接口**：`POST /api/auth/login`
- **权限**：公开
- **请求参数**：
```json
{
  "email": "string",     // 邮箱，必填
  "password": "string"   // 密码，必填
}
```
- **响应数据**：
```json
{
  "token": "string",
  "user": {
    "id": "string",
    "username": "string",
    "email": "string",
    "role": "user | admin"
  }
}
```

---

## 三、项目接口

### 3.1 获取项目列表
- **接口**：`GET /api/projects`
- **权限**：需登录
- **请求头**：`Authorization: Bearer {token}`
- **查询参数**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| page | number | 否 | 页码，默认1 |
| pageSize | number | 否 | 每页数量，默认10 |
| keyword | string | 否 | 搜索关键词（项目名称/描述） |
| sortBy | string | 否 | 排序字段：name/updatedAt/createdAt |
| sortOrder | string | 否 | 排序方向：asc/desc |

- **响应数据**：
```json
{
  "list": [
    {
      "id": "string",
      "name": "string",
      "description": "string",
      "sourceType": "git | zip",
      "repoUrl": "string",
      "status": "idle | parsing | ready | outdated | error",
      "diagramCount": 0,
      "updatedAt": "2024-01-01T00:00:00Z",
      "createdAt": "2024-01-01T00:00:00Z"
    }
  ],
  "pagination": {
    "page": 1,
    "pageSize": 10,
    "total": 100
  }
}
```

### 3.2 创建项目
- **接口**：`POST /api/projects`
- **权限**：需登录
- **请求参数**：
```json
{
  "name": "string",        // 项目名称，必填，2-50字符
  "description": "string", // 项目描述，选填
  "sourceType": "git | zip", // 接入方式，必填
  "repoUrl": "string",     // Git仓库地址，sourceType=git时必填
  "zipFileName": "string"  // ZIP文件名，sourceType=zip时必填
}
```
- **响应数据**：
```json
{
  "id": "string",
  "name": "string",
  "description": "string",
  "sourceType": "git | zip",
  "status": "idle",
  "diagramCount": 0,
  "updatedAt": "2024-01-01T00:00:00Z",
  "createdAt": "2024-01-01T00:00:00Z"
}
```

### 3.3 更新项目
- **接口**：`PUT /api/projects/{id}`
- **权限**：需登录，项目所有者
- **请求参数**：
```json
{
  "name": "string",
  "description": "string"
}
```

### 3.4 删除项目
- **接口**：`DELETE /api/projects/{id}`
- **权限**：需登录，项目所有者
- **响应数据**：无

### 3.5 获取文件树
- **接口**：`GET /api/projects/{id}/tree`
- **权限**：需登录，项目成员
- **响应数据**：
```json
[
  {
    "id": "string",
    "name": "string",
    "path": "string",
    "type": "directory | file",
    "children": [
      {
        "id": "string",
        "name": "string",
        "path": "string",
        "type": "file"
      }
    ]
  }
]
```

### 3.6 触发解析
- **接口**：`POST /api/projects/{id}/parse`
- **权限**：需登录，项目所有者
- **响应数据**：
```json
{
  "taskId": "string",
  "status": "pending"
}
```

### 3.7 同步代码
- **接口**：`POST /api/projects/{id}/sync`
- **权限**：需登录，项目所有者
- **响应数据**：
```json
{
  "taskId": "string",
  "status": "pending",
  "changes": {
    "added": [],
    "modified": [],
    "deleted": []
  }
}
```

### 3.8 上传ZIP
- **接口**：`POST /api/projects/{id}/upload-zip`
- **权限**：需登录，项目所有者
- **Content-Type**：`multipart/form-data`
- **请求参数**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | File | 是 | ZIP文件，最大50MB |

- **响应数据**：
```json
{
  "fileName": "string",
  "fileSize": 0,
  "uploadedAt": "2024-01-01T00:00:00Z"
}
```

---

## 四、图表接口

### 4.1 生成图表
- **接口**：`POST /api/projects/{id}/diagram/generate`
- **权限**：需登录，项目成员
- **请求参数**：
```json
{
  "instruction": "string",  // 生成指令，必填
  "type": "flowchart | sequenceDiagram | stateDiagram | classDiagram", // 图表类型，必填
  "selectedPaths": ["string"] // 选中的文件路径，选填
}
```
- **响应数据**：
```json
{
  "taskId": "string",
  "status": "pending"
}
```

### 4.2 获取图表
- **接口**：`GET /api/projects/{id}/diagram`
- **权限**：需登录，项目成员
- **响应数据**：
```json
{
  "id": "string",
  "projectId": "string",
  "title": "string",
  "type": "flowchart | sequenceDiagram | stateDiagram | classDiagram",
  "mermaidCode": "string",
  "version": 1,
  "outdated": false,
  "updatedAt": "2024-01-01T00:00:00Z",
  "sourceMap": {
    "节点名称": {
      "filePath": "string",
      "startLine": 1,
      "endLine": 10,
      "code": "string"
    }
  }
}
```

### 4.3 保存图表
- **接口**：`PUT /api/projects/{id}/diagram/{diagramId}`
- **权限**：需登录，项目成员
- **请求参数**：
```json
{
  "mermaidCode": "string",  // 修改后的Mermaid代码
  "title": "string"         // 图表标题，选填
}
```

### 4.4 导出图表
- **接口**：`POST /api/projects/{id}/diagram/{diagramId}/export`
- **权限**：需登录，项目成员
- **请求参数**：
```json
{
  "type": "svg | png | pdf | markdown"
}
```
- **响应数据**：
```json
{
  "fileName": "string",
  "mimeType": "string",
  "content": "string"  // base64编码或文本内容
}
```

### 4.5 分享图表
- **接口**：`POST /api/projects/{id}/diagram/{diagramId}/share`
- **权限**：需登录，项目成员
- **请求参数**：
```json
{
  "expireDays": 7,  // 过期天数，选填，默认7天
  "permission": "read"  // 权限：read，选填
}
```
- **响应数据**：
```json
{
  "shareUrl": "string",
  "expireAt": "2024-01-08T00:00:00Z"
}
```

---

## 五、任务接口（WebSocket）

### 5.1 连接WebSocket
- **接口**：`WS /ws/tasks/{taskId}`
- **权限**：需登录
- **请求头**：`Authorization: Bearer {token}`

### 5.2 任务进度事件
- **推送方向**：服务端 → 客户端
- **消息格式**：
```json
{
  "taskId": "string",
  "type": "parse | sync | diagram",
  "progress": 35,
  "status": "pending | running | success | error",
  "message": "解析仓库结构与业务节点",
  "updatedAt": "2024-01-01T00:00:00Z"
}
```

### 5.3 任务状态说明
| 状态 | 说明 |
|------|------|
| pending | 等待执行 |
| running | 执行中 |
| success | 执行成功 |
| error | 执行失败 |
| canceled | 已取消 |

---

## 六、管理员接口

### 6.1 获取概览统计
- **接口**：`GET /api/admin/overview`
- **权限**：管理员
- **响应数据**：
```json
{
  "userCount": 100,
  "projectCount": 50,
  "taskCount": 200,
  "successRate": 95.5,
  "activeUsers": 20
}
```

### 6.2 获取用户列表
- **接口**：`GET /api/admin/users`
- **权限**：管理员
- **查询参数**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| page | number | 否 | 页码 |
| pageSize | number | 否 | 每页数量 |
| keyword | string | 否 | 搜索关键词 |

- **响应数据**：
```json
{
  "list": [
    {
      "id": "string",
      "username": "string",
      "email": "string",
      "role": "user | admin",
      "lastActiveAt": "2024-01-01T00:00:00Z",
      "projectCount": 5
    }
  ],
  "pagination": {
    "page": 1,
    "pageSize": 10,
    "total": 100
  }
}
```

### 6.3 获取任务列表
- **接口**：`GET /api/admin/tasks`
- **权限**：管理员
- **查询参数**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| page | number | 否 | 页码 |
| pageSize | number | 否 | 每页数量 |
| status | string | 否 | 状态筛选 |

- **响应数据**：
```json
{
  "list": [
    {
      "taskId": "string",
      "projectId": "string",
      "type": "parse | sync | diagram",
      "status": "pending | running | success | error",
      "progress": 100,
      "message": "string",
      "createdAt": "2024-01-01T00:00:00Z",
      "updatedAt": "2024-01-01T00:00:00Z"
    }
  ],
  "pagination": {
    "page": 1,
    "pageSize": 10,
    "total": 100
  }
}
```

### 6.4 更新用户配额
- **接口**：`PATCH /api/admin/quotas/{user_id}`
- **权限**：管理员
- **请求参数**：
```json
{
  "maxProjects": 10,
  "maxDiagramsPerProject": 50,
  "maxStorageSize": 1073741824
}
```

### 6.5 获取审计日志
- **接口**：`GET /api/admin/audit-logs`
- **权限**：管理员
- **查询参数**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| page | number | 否 | 页码 |
| pageSize | number | 否 | 每页数量 |
| userId | string | 否 | 用户ID筛选 |
| action | string | 否 | 操作类型筛选 |
| startDate | string | 否 | 开始日期 |
| endDate | string | 否 | 结束日期 |

- **响应数据**：
```json
{
  "list": [
    {
      "id": "string",
      "userId": "string",
      "username": "string",
      "action": "string",
      "resource": "string",
      "ip": "string",
      "userAgent": "string",
      "createdAt": "2024-01-01T00:00:00Z"
    }
  ],
  "pagination": {
    "page": 1,
    "pageSize": 10,
    "total": 100
  }
}
```

---

## 七、数据模型

### 7.1 用户模型
```typescript
interface User {
  id: string
  username: string
  email: string
  password: string  // 加密存储
  role: 'user' | 'admin'
  createdAt: Date
  updatedAt: Date
}
```

### 7.2 项目模型
```typescript
interface Project {
  id: string
  name: string
  description: string
  sourceType: 'git' | 'zip'
  repoUrl?: string
  zipFilePath?: string
  status: 'idle' | 'parsing' | 'ready' | 'outdated' | 'error'
  diagramCount: number
  ownerId: string
  createdAt: Date
  updatedAt: Date
}
```

### 7.3 图表模型
```typescript
interface Diagram {
  id: string
  projectId: string
  title: string
  type: 'flowchart' | 'sequenceDiagram' | 'stateDiagram' | 'classDiagram'
  mermaidCode: string
  version: number
  outdated: boolean
  sourceMap: Record<string, {
    filePath: string
    startLine: number
    endLine: number
    code: string
  }>
  createdAt: Date
  updatedAt: Date
}
```

### 7.4 任务模型
```typescript
interface Task {
  id: string
  projectId: string
  type: 'parse' | 'sync' | 'diagram'
  status: 'pending' | 'running' | 'success' | 'error' | 'canceled'
  progress: number
  message: string
  result?: any
  error?: string
  createdAt: Date
  updatedAt: Date
}
```

---

## 八、前端Mock切换说明

### 8.1 关闭Mock
设置环境变量：
```bash
VITE_ENABLE_MOCK=false
```

### 8.2 Mock文件位置
- `src/api/mock.ts` - 所有Mock数据和方法
- `src/api/http.ts` - Mock开关控制

### 8.3 需要清理的依赖
- `src/stores/taskStore.ts` 第4行直接引用 `mock.ts`
- 关闭Mock后需要改为WebSocket连接

---

## 九、开发优先级建议

| 优先级 | 接口 | 说明 |
|--------|------|------|
| 🔴 P0 | 登录/注册 | 基础认证 |
| 🔴 P0 | 项目CRUD | 核心功能 |
| 🔴 P0 | 文件树 | 仓库解析 |
| 🔴 P0 | 图表生成 | AI解析服务 |
| 🟡 P1 | WebSocket进度 | 实时推送 |
| 🟡 P1 | 导出/分享 | 文件服务 |
| 🟢 P2 | 管理员后台 | 管理功能 |
| 🟢 P2 | 审计日志 | 监控功能 |
