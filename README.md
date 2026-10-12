# AI-Code-Visualizer

AI-Code-Visualizer 用于读取代码仓库、建立源码索引，并生成和编辑 Mermaid 图表。项目采用 Vue 3 + TypeScript 前端、FastAPI + SQLAlchemy 后端，默认使用 SQLite，支持在本地启动和演示。

## 项目内容

| 目录 | 内容 |
| --- | --- |
| `backend/` | 接口、鉴权、项目管理、上传、源码解析、图表生成、数据库迁移和后端测试 |
| `frontend/` | 登录、项目列表、工作区、图表画布、源码查看、导出和前端测试 |
| `examples/semester-acceptance/` | 可用于上传、解析和生成结构图的 Python 示例 |
| `docs/` | 本次整理的检查结果及 GitHub 上传说明 |

## 当前功能与边界

- 注册、登录和项目管理；支持 ZIP 上传，以及不含凭据的公开 GitHub HTTPS 仓库导入。
- Python 文件扫描、函数/类/方法提取、依赖分析、代码分块、全量解析和增量同步。
- 流程图、类图、时序图和状态图的生成、Mermaid 编辑、保存，以及 Markdown、SVG、PNG、PDF 导出。
- 可接入 OpenAI 兼容接口的大模型；未启用模型或调用失败时，提供明确提示及规则生成的降级结果。
- 查询任务状态和错误原因；后台提供已有指标、用户、任务及审计信息。

Python 是当前主要语义解析语言。其他扩展名被接纳或展示，不表示已有完整语言解析器。模型生成图和规则图均需要使用者核对业务关系；任务成功不等于业务图准确。

目前没有完整的通用聊天、实时推送、公开分享读取、历史版本管理或配额计费功能。源码点击定位以已有映射的流程图节点为主。Celery/Redis 相关文件保留为基础框架，当前本地主要流程通过现有服务直接执行。

## 环境要求

- Python 3.11 为项目目标环境。
- Node.js 18 或更高版本，及 npm。
- 使用 Git 仓库导入时，需安装 Git 并确保命令可用。

以下启动命令以 Windows PowerShell 为例。首次安装依赖需要联网。

## 启动后端

在项目根目录打开 PowerShell：

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m alembic upgrade head
python -m alembic current
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

`Copy-Item` 用于第一次创建本地配置；已有 `.env` 时，保留自己的配置，不要覆盖真实密钥或数据库地址。

启动后可访问：

- 健康检查：`http://127.0.0.1:8000/health`
- 由真实路由生成的接口文档：`http://127.0.0.1:8000/docs`

## 启动前端

新开一个 PowerShell，在项目根目录执行：

```powershell
cd frontend
npm ci
Copy-Item .env.example .env
npm run dev
```

前端默认地址为 `http://localhost:5173`。示例配置使用真实后端：

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_DEV_BACKEND_URL=http://127.0.0.1:8000
VITE_ENABLE_MOCK=false
```

如果后端改用其他端口，上面两个地址也要同步修改。修改前端 `.env` 后重启 Vite。

## 大模型配置

本地不接入模型时，在 `backend/.env` 中设置：

```env
LLM_ENABLED=off
LLM_API_KEY=
LLM_MAX_CONTEXT_CHARS=12000
```

接入与 OpenAI 接口兼容的模型服务时，填写实际服务提供的信息：

```env
LLM_ENABLED=true
LLM_API_KEY=填写自己的API密钥
LLM_BASE_URL=填写服务地址
LLM_MODEL=填写模型名称
LLM_MAX_CONTEXT_CHARS=12000
```

修改后重启后端。真实 `.env` 和密钥不提交到 GitHub；仓库只保留不含真实密钥的 `.env.example` 模板。

## 数据库升级

当前迁移终点为 `20261011_0003`。已有数据库升级前，应停止写入并备份数据库及 `storage`，随后在后端目录执行：

```powershell
python -m alembic upgrade head
python -m alembic current
```

升级后的旧项目需要执行一次全量重新解析，重建当前源码索引。无变化同步不能替代旧索引格式升级。不要通过删除数据库、手改项目状态或索引版本跳过升级。

新的迁移区分“模型用量已采集”和“未采集”，不把历史记录的零值视为真实用量。当前不根据这些字段进行计费。

## 本地演示流程

1. 注册并登录。
2. 将 `examples/semester-acceptance/` 中的示例源码打成 ZIP，或选择自己的 Python 项目。
3. 上传 ZIP 并创建项目；也可导入符合要求的公开 GitHub 仓库。
4. 执行全量解析，查看任务是否成功及文件树是否生成。
5. 选择文件、图表类型，在右侧输入生成要求并提交。
6. 核对图表内容，按需编辑、保存及导出。

生成接口返回失败时，查看任务编号和失败原因。遇到旧索引或源码变化的冲突，应确认当前上传来源、完成解析，再重新生成。

## 检查命令

后端在虚拟环境激活后执行：

```powershell
cd backend
python -m pytest tests -q
```

前端执行：

```powershell
cd frontend
npm test
npm run check
npm run lint
npm run build
```

测试使用临时数据库和临时存储，不需要提交运行数据库。当前整理包的实际检查范围、结果和上传注意事项见 [检查与上传说明]。
