# AI仓库业务流程可视化平台 

本仓库包含完整的后端与前端实现。


**后端**：FastAPI后端骨架、数据库模型、Alembic迁移、核心REST接口、统一响应、权限校验、上传
表接口、后台管理接口，以及基础测试用例。


**前端**：Vue 3 + TypeScript + Vite 构建的 SPA 前端，包含完整的项目管理和可视化工作台。


## 1. 已完成内容

### 后端
- FastAPI项目骨架：`app/main.py`、路由分层、Service层、Repository风格的数据访问封装。
- 数据库设计落地：`users/projects/repositories/source_files/code_chunks/symbols/dependencies/analysis_tasks/diagrams/agent_runs/quotas/audit_logs`。
- Alembic迁移：`migrations/versions/20260509_0001_initial_schema.py`。
- 鉴权：注册、登录、JWT、密码哈希、普通用户/管理员权限。
- 核心接口：认证、项目CRUD、ZIP上传、解析任务、同步任务、分析任务、图表查询/保存/导出/分享、后台指标。
- 安全基础：ZIP路径穿越校验、文件大小限制、项目owner校验、管理员接口role校验、统一错误结构。
- 可演示闭环：注册/登录 -> 创建项目 -> 上传ZIP -> 触发解析任务 -> 生成Mermaid图 -> 查询/编辑/导出。

### 前端
- 技术栈：Vue 3 + TypeScript + Vite 5、Pinia 状态管理、Vue Router 4、Tailwind CSS、Mermaid 图表渲染、Axios 请求封装。
- 认证系统：登录/注册页面、JWT 本地持久化、路由守卫、普通用户/管理员权限分流。
- 项目列表：项目搜索与分页、多选/全选/批量操作（解析、同步、删除）、新建/编辑项目弹窗、Git / ZIP 两种接入方式。
- 工作台：四面板拖拽布局（文件树 / Mermaid 画布 + 源码编辑器 / 源码面板 / AI指令 + 进度）、文件多选过滤。
- 图表交互：Mermaid 实时渲染、缩放/平移/拖拽/重绘、节点点击溯源、源码行级高亮。
- 导出与分享：支持 SVG / PNG / PDF / Markdown 四种导出格式、分享链接生成与复制。
- 管理后台：用户列表与角色管理、任务监控面板、统计概览卡。
- Mock 数据层：内置完整 Mock 适配器，无需后端即可全链路演示（含模拟 WebSocket 任务推送）。
- 编辑器：底部 Mermaid 源码编辑器支持手动修改、实时重绘与保存。

## 2. 目录结构

```text
backend/
  app/
    main.py                  # FastAPI入口
    api/                     # Router层
    core/                    # 配置、数据库、鉴权、统一响应、异常
    models/                  # SQLAlchemy ORM模型
    schemas/                 # Pydantic DTO
    services/                # 业务服务层
    repositories/            # 数据访问辅助
    agents/                  # 多Agent编排占位实现
    tasks/                   # Celery配置与任务入口
    tools/                   # ZIP安全、哈希、Mermaid校验
    parsing/                 # 源码解析具体实现
  migrations/                # Alembic迁移
  tests/                     # pytest测试

frontend/
  public/                              # 静态资源（favicon）
  src/
    App.vue                            # 根组件（仅渲染 <router-view />）
    main.ts                            # 应用入口（挂载 Vue / Pinia / Router + 全局样式）
    vite-env.d.ts                      # Vite 环境类型声明
    api/                               # API 请求层
    components/                        # 公共组件
    router/                            # Vue Router 路由配置
    stores/                            # Pinia 状态管理
    styles/                            # 全局样式
    types/                             # TypeScript 类型定义
    utils/                             # 工具函数
    views/                             # 页面级视图
  .env.example                         # 环境变量模板
  .eslintrc.cjs                        # ESLint 配置（Vue 3 + TypeScript + Prettier）
  .gitignore                           # Git 忽略规则
  .prettierrc.json                     # Prettier 配置（单引号/无分号/尾逗号）
  index.html                           # HTML 入口
  package.json                         # 项目依赖与脚本
  package-lock.json                    # 依赖锁定文件
  postcss.config.js                    # PostCSS 配置
  tailwind.config.js                   # Tailwind CSS 配置
  tsconfig.json                        # TypeScript 配置（@ 别名）
  vite.config.ts                       # Vite 构建配置（Vue 插件/路径别名/测试配置）
```

## 3. 本地运行

### 后端
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

打开接口文档：`http://127.0.0.1:8000/docs`

### 前端
```bash
cd frontend    # 进入 frontend 目录
npm install    # 安装依赖
npm run dev    # 开发模式运行
npm run build  # 构建生产版本
npm run check  # 代码检查
npm run lint   # 代码检查
npm run test   # 运行测试
```

打开应用：`http://localhost:5173`


## 4. 使用PostgreSQL（暂时不需要用到，因为用的是SQLite本地数据库）

`.env`中设置：

```env
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/ai_code_visualizer
```

然后执行：

```bash
alembic upgrade head
```

## 5. 运行测试

```bash
pytest -q
```
测试默认使用SQLite临时数据库，不影响开发数据库。


##6.源码解析具体实现

### 6.1 解析流程

```
ZIP上传 → scan_zip (文件扫描过滤)
        → tree_parser 
                    → def parse_source (Tree-sitter提取符号)
        → symbol_extractor 
                    → def extract_and_save (写入symbols表)
        → chunker 
                    → def chunk_and_save (按符号边界切块)
        → dependency_analyzer 
                    → def extract_imports (import依赖分析)
```

### 6.2 全量解析 (parse_full)

`IndexService.parse_full()` 编排整个管线：

1. `scan_zip` — 遍历 ZIP，过滤 `.git/node_modules/dist/...`，按扩展名识别语言，写入 `source_files`
2. `parse_source` — Tree-sitter 解析 Python 源码，提取类/函数/方法（含装饰器展开），产出 `SymbolInfo`
3. `extract_and_save` — 符号写入 `symbols`
4. `chunk_and_save` — 按符号起止行号切片源码，写入 `code_chunks`
5. `extract_imports` — `ast` 模块解析 import，跨文件匹配，写入 `dependencies`  (目前只支持python语言)

### 6.3 增量同步 (sync_incremental)

用于项目更新后只处理变化部分：

1. `scan_zip_inventory` — 只读扫描新 ZIP，不写库
2. 与 `source_files` 现有数据对比 hash，分出 `added / modified / deleted`
3. 变更文件执行对应操作（新增→解析、修改→删旧重解析、删除→清理关联）
4. 重建项目所有依赖
5. 标记引用了变更文件的图表为 `is_outdated`

### 6.4 模块职责

| 模块 | 职责 |
|------|------|
| `file_scanner.py` | ZIP遍历、路径过滤、语言识别、sha256哈希。`scan_zip` 写库，`scan_zip_inventory` 只读 |
| `tree_parser.py` | Tree-sitter 解析，提取 class/function/method，展开 `decorated_definition` |
| `symbol_extractor.py` | `SymbolInfo` 列表写入 `symbols` |
| `chunker.py` | 按 start_line/end_line 切片源码，写入 `code_chunks` |
| `dependency_analyzer.py` | `ast` 解析 import，模块路径匹配文件，反查符号表获取 `target_symbol_id` |
| `__init__.py` | `parse_project()` 编排上述步骤，返回统计信息 |

### 6.5 分层设计

- **解析层** (`app/parsing/`)：纯解析逻辑，不依赖 API/Service 层
- **服务层** (`app/services/index_service.py`)：调用解析管线，管理任务状态、进度、异常

### 6.6 测试

```bash
python tests/test_parsing.py
```
需要两次运行实现： `storage/vue3.zip`，第二次加入 `storage/vue3_v2.zip`（增量同步测试用）。





## 7. 说明

当前版本把耗时任务先做成“可联调的同步占位实现”：解析/同步任务会写入`analysis_tasks`表，图表生成使用`AgentOrchestrator`模拟Mermaid输出。后续源码解析负责人和AI/Agent负责人可以替换`IndexService`和`AgentOrchestrator`内部逻辑，不需要改接口契约。
