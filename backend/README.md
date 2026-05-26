# AI仓库业务流程可视化平台 - 后端工程

本目录是“后端负责人”交付物：FastAPI后端骨架、数据库模型、Alembic迁移、核心REST接口、统一响应、权限校验、上传安全校验、任务与图表接口、后台管理接口，以及基础测试用例。

## 1. 已完成内容

- FastAPI项目骨架：`app/main.py`、路由分层、Service层、Repository风格的数据访问封装。
- 数据库设计落地：`users/projects/repositories/source_files/code_chunks/symbols/dependencies/analysis_tasks/diagrams/agent_runs/quotas/audit_logs`。
- Alembic迁移：`migrations/versions/20260509_0001_initial_schema.py`。
- 鉴权：注册、登录、JWT、密码哈希、普通用户/管理员权限。
- 核心接口：认证、项目CRUD、ZIP上传、解析任务、同步任务、分析任务、图表查询/保存/导出/分享、后台指标。
- 安全基础：ZIP路径穿越校验、文件大小限制、项目owner校验、管理员接口role校验、统一错误结构。
- 可演示闭环：注册/登录 -> 创建项目 -> 上传ZIP -> 触发解析任务 -> 生成Mermaid图 -> 查询/编辑/导出。

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
  migrations/                # Alembic迁移
  tests/                     # pytest测试
```

## 3. 本地运行

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

打开接口文档：`http://127.0.0.1:8000/docs`

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

## 6. 说明

当前版本把耗时任务先做成“可联调的同步占位实现”：解析/同步任务会写入`analysis_tasks`表，图表生成使用`AgentOrchestrator`模拟Mermaid输出。后续源码解析负责人和AI/Agent负责人可以替换`IndexService`和`AgentOrchestrator`内部逻辑，不需要改接口契约。
