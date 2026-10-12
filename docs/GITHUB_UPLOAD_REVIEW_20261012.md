# 源码检查与 GitHub 上传说明

检查日期：2026-10-12。输入文件：`backend.zip`。虽然文件名写的是 backend，包内实际上包含完整的前端和后端工程。

## 1. 检查结论

本次整理针对上传文件、工程说明和忽略规则。输入包有 212 个文件，移出 27 个文件，保留 185 个原文件，新增本说明后，上传包共有 186 个文件。

保留的业务源码、测试、数据库迁移、依赖清单和前端锁文件均与输入包逐字节一致。移出的 Python 文件只有空白的 `backend/app/parsing/init.py`；它不是 `__init__.py`，且源码和测试中均没有引用。所有正式的 `__init__.py` 都予以保留。

本次没有修改功能逻辑或依赖版本。修改的原文件为：

| 文件 | 整理内容 |
| --- | --- |
| `.gitignore` | 补充配置变体、缓存、SQLite 附属文件、类型检查产物、AI 编辑器目录和本地交付包的排除规则 |
| `backend/.gitignore` | 补充环境配置变体、SQLite 附属文件和完整运行存储目录的排除规则 |
| `frontend/.gitignore` | 补充真实配置、类型检查产物、覆盖率和 AI 编辑器目录的排除规则 |
| `README.md` | 改为完整项目说明，保留启动、模型配置、数据库升级、检查命令和实际功能边界 |
| `backend/README.md` | 更新后端模块说明及迁移终点，统一引用项目启动说明 |
| `frontend/README.md` | 用本项目的启动、配置和检查步骤替换 Vite 模板介绍 |

## 2. 最新版与 GitHub 仓库的对照范围

可读取的仓库 main 根目录包括 `app/`、`migrations/`、`tests/` 和后端配置文件；本次输入包使用 `backend/`、`frontend/`、`examples/` 的完整工程结构。这是上传时必须处理的目录变化。

当前源码包含真实的 Python 扫描、解析、依赖分析和索引服务，大模型接口与源码上下文构建，以及前端项目工作区、图表编辑和导出。保留了上传绑定、索引来源校验、任务失败处理、无变化同步和模型用量记录相关实现及回归测试。

本次可以读取 GitHub 仓库首页和 `requirements.txt`，但无法取得远程全部源码，输入包也没有 Git 历史。因此，上述内容是当前源码检查和可读取仓库信息的对照，不能当作相对远程 main 的完整逐文件差异清单。上传前应在克隆的仓库中暂存改动，通过 VS Code 的差异视图查看最终新增、修改和删除内容。

仓库参考：<https://github.com/xuke-shake/AI-Code-Visualizer>。

## 3. 排除的文件

| 类别 | 数量 | 原因 |
| --- | ---: | --- |
| `frontend/.trae/documents/` | 2 | AI 编辑器生成的旧需求和架构草稿，不参与启动或测试 |
| 原 `docs/` 下的修复日志、环境 JSON、微基准和执行计划 | 21 | 开发过程材料，包含本机路径和历史轮次结果，不适合作为当前项目操作说明 |
| 两份过时的交付或接口草稿 | 2 | 仍描述占位解析、旧测试数、未接通的 WebSocket 或公开分享，容易误导使用者 |
| `_make_source_archive.ps1` | 1 | 交付阶段的打包辅助文件，项目启动、构建和测试均不依赖 |
| `backend/app/parsing/init.py` | 1 | 空白且未引用的占位文件 |

历史记录仍存在于原上传包中。新的源码包使用当前 README、真实后端接口文档和本次检查结果作为阅读入口。

排除清单：

```text
_make_source_archive.ps1
backend/app/parsing/init.py
backend/docs/backend-deliverable.md
docs/BUGFIX_RESULT.md
docs/FIRST_SEMESTER_FINAL_ACCEPTANCE_20261011.md
docs/FIRST_SEMESTER_FINAL_BROWSER_20261011.json
docs/FIRST_SEMESTER_FINAL_CHECKS_20261011.json
docs/FIRST_SEMESTER_FINAL_VERSIONS_20261011.json
docs/R02_AB_FIX_RESULT_20261011.md
docs/R04_A2_DE_FIX_RESULT_20261011.md
docs/R04_A2_DE_MICROBENCH_20261011.json
docs/R04_A2_DE_VERSIONS_20261011.json
docs/R04_D2_D3_FIX_RESULT_20261011.md
docs/R04_D2_D3_MICROBENCH_20261011.json
docs/R04_D2_D3_VERSIONS_20261011.json
docs/R04_D4_D5_FIX_RESULT_20261011.md
docs/R04_D4_D5_VERSIONS_20261011.json
docs/R04_R05_MICROBENCH_20261011.json
docs/R04_R05_SUPPLEMENT_RESULT_20261011.md
docs/R04_R05_SUPPLEMENT_VERSIONS_20261011.json
docs/R04_R06_DEPENDENCY_VERSIONS_20261011.json
docs/R04_R06_FIX_RESULT_20261011.md
docs/superpowers/plans/2026-10-11-first-semester-final.md
docs/superpowers/plans/FIRST_SEMESTER_SCOPE_20261011.md
frontend/.trae/documents/产品需求文档.md
frontend/.trae/documents/技术架构文档.md
frontend/API接口文档.md
```

## 4. 需要保留的工程文件

- `backend/tests/` 和前端 `*.spec.ts`：正式回归测试，不是运行缓存。
- 全部数据库迁移：初始结构、上传记录迁移及模型用量标记迁移。当前迁移终点为 `20261011_0003`。
- `requirements.txt`、`package.json` 和 `package-lock.json`：用于安装并保持依赖一致。
- 前后端 `.env.example`：只包含占位配置；模型 API 密钥为空。
- `frontend/src/api/mock.ts`：开发和测试需要，保留文件不会自动开启 Mock。
- 示例源码、前端构建配置和必要资源。
- Celery/Redis 和 Docker 相关基础配置：属于工程文件；当前本地主要流程不要求运行 Worker。

前端配置仍保留开发工具定位插件和 Trae 徽标插件，包名仍为 `trae-project`。这些并非缓存文件，本轮保留了相应配置和依赖，未改变页面行为或锁文件。

## 5. 本次实际验证

运行环境为 Linux、Python 3.12.14、Node.js 24.19.0、npm 11.9.0。项目目标 Python 版本为 3.11，本次没有在 Windows/Python 3.11 环境中执行。

| 检查 | 实际结果 |
| --- | --- |
| 从 `requirements.txt` 安装后端依赖 | 成功，退出码 0 |
| `python -m pip check` | 无依赖冲突，退出码 0 |
| 后端 pytest 全量 | 416 passed，0 skipped，退出码 0 |
| `npm ci --no-audit --no-fund` | 成功，退出码 0 |
| 前端 Vitest | 15 个测试文件、55 项测试全部通过，退出码 0 |
| `npm run check` | 通过，退出码 0 |
| `npm run lint` | 通过，退出码 0 |
| `npm run build` | 通过，退出码 0 |
| Python 静态语法检查 | 110 个保留的 Python 文件可解析，无语法错误 |
| 锁文件核对 | 与 `package.json` 的直接依赖声明一致，两个文件均未修改 |

前端测试实际命令为 `npm test -- --maxWorkers=2 --minWorkers=1`，限制并行数以适应检查环境。后端测试使用临时数据库、临时存储，并关闭真实模型调用。

测试和安装存在弃用提示；后端测试报告 1659 条 warnings，前端构建报告部分分块超过 500 kB。它们没有导致本次检查失败，本轮未实施依赖升级或性能优化。

对保留文件的常见 API 密钥、GitHub token、云访问密钥和私钥格式进行了扫描，未发现匹配；前后端模板均无真实模型密钥。该扫描不等同于证明所有文件绝对不含敏感信息。

本次没有重新进行真实浏览器手工点击、远程模型调用或远程 Git 导入验收，也没有取得远程全部代码进行精确差异比较。自动测试通过不代表模型生成的业务图必然准确。

## 6. 使用 VS Code 更新已有仓库

1. 在 VS Code 克隆已有 GitHub 仓库，打开克隆目录。保留该目录中的 `.git`，它保存仓库关联和历史。
2. 先备份本地目录，确认要更新的分支；可创建更新分支后再提交，方便组员查看。
3. 在复制新包之前，创建 `backend/`，将旧仓库根目录的后端文件移入对应位置，再用本包覆盖更新。不要同时保留根目录的旧后端和 `backend/` 中的新后端。
4. 将解压后 `AI-Code-Visualizer/` 文件夹里面的内容复制到克隆目录。不要把整个外层文件夹再嵌套一层。
5. 对照排除清单处理旧版本残留文件；远程仓库中未包含在本次输入包里的独有文档，应另行核对用途，不要批量删除。
6. 打开“源代码管理”，检查改动，再暂存需要上传的文件。查看暂存差异，确认新增前端、后端目录迁移和旧文件删除都符合预期。
7. 填写提交说明并 Commit，随后 Push；如果使用更新分支，再通过 Pull Request 合并。

旧后端文件的目录对应关系：

| 旧根目录位置 | 新位置 |
| --- | --- |
| `app/` | `backend/app/` |
| `migrations/` | `backend/migrations/` |
| `tests/` | `backend/tests/` |
| `alembic.ini` | `backend/alembic.ini` |
| `requirements.txt` | `backend/requirements.txt` |
| `pyproject.toml` | `backend/pyproject.toml` |
| `docker-compose.yml` | `backend/docker-compose.yml` |
| `.env.example` | `backend/.env.example` |
| `.gitignore`、`README.md` | 根目录保留，更新为本包的完整项目版本 |

`.gitignore` 只阻止未跟踪文件被自动加入，不能自动移除已经提交过的文件。若本地配置或数据库此前已被跟踪，应解除 Git 跟踪，同时保留自己的本地数据。

提交说明示例：`整理完整前后端项目，补齐启动说明并清理开发过程文件`。
