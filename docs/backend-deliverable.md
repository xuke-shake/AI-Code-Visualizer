# 后端负责人交付说明

## 一、交付范围

1. 把控后端开发进度，明确MVP优先级。
2. 设计数据库表、关系、索引与迁移脚本。
3. 实现FastAPI项目骨架、统一响应、鉴权、权限校验、核心接口。
4. 提供可运行、可测试、可继续接入源码解析与AI Agent模块的基础框架。

## 二、已实现模块

| 模块 | 已完成内容 |
|---|---|
| 用户权限与项目管理 | 注册、登录、JWT、当前用户、项目CRUD、项目配置读写 |
| 仓库解析与数据接入 | ZIP上传安全校验、解析任务接口、任务状态接口、SSE进度接口 |
| 增量同步与索引更新 | 同步任务接口、变更列表接口、图表过期刷新接口占位 |
| 业务逻辑提取与动态图表 | 分析任务接口、AgentOrchestrator占位实现、Mermaid生成、节点映射保存 |
| 导出分享 | Markdown/SVG导出接口、分享链接接口 |
| 运维与管理 | 用户列表、任务列表、指标统计、配额更新、审计日志查询 |

## 三、数据库表

本工程通过SQLAlchemy模型和Alembic迁移实现以下表：

| 表名 | 用途 |
|---|---|
| users | 用户账号、密码哈希、角色、状态 |
| quotas | 用户项目数、文件数、并发任务、Token配额 |
| projects | 分析项目、语言、来源类型、状态、配置 |
| repositories | Git/ZIP来源、分支、commit、对象存储路径 |
| source_files | 源码文件路径、语言、哈希、解析状态 |
| code_chunks | 代码块内容、起止行、摘要、向量ID |
| symbols | 函数、类、方法、导入等符号 |
| dependencies | 调用、导入、继承等依赖关系 |
| analysis_tasks | 解析、同步、图表、导出任务进度 |
| diagrams | Mermaid源码、图表类型、节点映射、版本 |
| agent_runs | Agent输入输出摘要、模型、Token、耗时、错误 |
| audit_logs | 项目、上传、登录、后台操作审计 |

## 四、核心接口清单

### Auth

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/auth/register | 注册账号 |
| POST | /api/auth/login | 登录并返回JWT |
| GET | /api/auth/me | 查询当前用户 |

### Projects

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/projects | 分页查询项目 |
| POST | /api/projects | 创建项目 |
| GET | /api/projects/{project_id} | 查询项目详情 |
| PATCH | /api/projects/{project_id} | 更新项目 |
| DELETE | /api/projects/{project_id} | 删除项目 |
| GET | /api/projects/{project_id}/config | 获取项目配置 |
| PATCH | /api/projects/{project_id}/config | 保存项目配置 |
| POST | /api/projects/{project_id}/parse | 触发解析任务 |
| POST | /api/projects/{project_id}/sync | 触发同步任务 |
| GET | /api/projects/{project_id}/changes | 查询变更列表 |

### Uploads / Tasks

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/uploads | 上传ZIP包 |
| GET | /api/tasks/{task_id} | 查询任务状态 |
| GET | /api/tasks/{task_id}/events | SSE任务进度 |

### Analysis / Diagrams

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/projects/{project_id}/analysis | 创建图表分析任务 |
| GET | /api/analysis/{task_id} | 查询分析任务 |
| GET | /api/diagrams/{diagram_id} | 获取图表详情 |
| PATCH | /api/diagrams/{diagram_id} | 编辑并保存Mermaid |
| POST | /api/diagrams/{diagram_id}/refresh | 刷新过期图表标记 |
| POST | /api/diagrams/{diagram_id}/export | 导出图表 |
| POST | /api/diagrams/{diagram_id}/share | 生成分享链接 |

### Admin

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/admin/metrics | 后台指标 |
| GET | /api/admin/users | 用户列表 |
| GET | /api/admin/tasks | 任务列表 |
| PATCH | /api/admin/quotas/{user_id} | 修改用户配额 |
| GET | /api/admin/audit-logs | 审计日志 |

## 五、运行与测试结果

已完成本地校验：

```bash
python -m compileall -q app tests migrations
pytest -q
```

测试结果：

```text
2 passed
```

## 六、后续对接建议

1. 源码解析负责人替换 `app/services/index_service.py` 中的占位解析逻辑，写入 `source_files/code_chunks/symbols/dependencies`。
2. AI/Agent负责人替换 `app/agents/orchestrator.py`，接入真实RAG、LLMProvider和EmbeddingProvider。
3. 图表负责人可继续增强 `app/services/export_service.py`，接入无头浏览器或前端导出PNG/PDF。
4. 测试负责人可扩展 `tests/`，覆盖上传ZIP、权限越权、管理员接口、非法Mermaid等异常路径。
