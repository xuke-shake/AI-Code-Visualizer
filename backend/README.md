# AI-Code-Visualizer 后端

后端使用 FastAPI、SQLAlchemy 和 SQLite，提供账号鉴权、项目管理、ZIP 上传、Git 导入、Python 源码索引、图表生成与保存、任务查询和管理端接口。

| 目录 | 用途 |
| --- | --- |
| `app/api/` | REST 路由与请求处理 |
| `app/core/` | 配置、数据库连接、权限和统一响应 |
| `app/models/`、`app/schemas/` | 数据模型和接口数据结构 |
| `app/parsing/` | 文件扫描、符号提取、依赖分析和代码分块 |
| `app/services/` | 项目、上传、索引、图表等业务服务 |
| `app/agents/` | 源码上下文构建、模型接口和图表生成 |
| `app/tasks/` | Celery 基础框架；当前本地主要流程不依赖 Worker |
| `migrations/` | 数据库迁移，当前终点为 `20261011_0003` |
| `tests/` | 上传、权限、解析、生成、同步、迁移等回归测试 |

完整的 Windows 启动、模型配置和旧数据库升级步骤见 [项目启动说明](../README.md)。从本目录启动后，可访问 `http://127.0.0.1:8000/docs` 查看真实接口定义。

激活后端虚拟环境后，在本目录运行测试：

```powershell
python -m pytest tests -q
```

测试使用临时 SQLite 数据库和临时存储。`requirements.txt`、`migrations/` 和 `.env.example` 是必要的工程文件，应保留在仓库；真实 `.env`、数据库及 `storage/` 由本地运行生成。
