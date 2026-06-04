# AI-Code-Visualizer 项目启动说明

## 一、环境要求

本项目分为后端和前端两部分，项目目录大致如下：

```text
项目根目录/
  backend/
  frontend/
```

需要提前安装：

```text
Python 3.11
Node.js 18+
npm
```

注意：后端建议使用 Python 3.11，不建议使用 Python 3.12 或 Python 3.13，因为部分 Tree-sitter 相关依赖在高版本 Python 下可能安装失败。

---

## 二、启动后端

进入后端目录：

```powershell
cd 项目路径\backend
```

如果还没有虚拟环境，先创建虚拟环境：

```powershell
py -3.11 -m venv .venv
```

激活虚拟环境：

```powershell
.\.venv\Scripts\activate
```

安装依赖：

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

---

## 三、配置后端 `.env`

在后端目录下找到或新建：

```text
backend/.env
```

如果暂时不接入大模型，可以这样配置：

```env
LLM_ENABLED=auto
LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=
LLM_MAX_CONTEXT_CHARS=12000
```

如果要接入 DeepSeek API，可以这样配置：

```env
LLM_ENABLED=true
LLM_API_KEY=你的DeepSeek_API_Key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
LLM_MAX_CONTEXT_CHARS=12000
```

注意：

```text
LLM_API_KEY 不要提交到 GitHub，也不要截图发给别人。
LLM_BASE_URL 不要写 /anthropic，直接写 https://api.deepseek.com。
```

---

## 四、启动后端服务

如果 8000 端口没有被占用，可以使用：

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --access-log --log-level debug
```

如果 8000 端口被占用，可以改用 8001：

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --access-log --log-level debug
```

启动成功后，终端应该看到类似：

```text
Uvicorn running on http://127.0.0.1:8001
Application startup complete.
```

可以在浏览器访问下面地址测试后端是否启动成功：

```text
http://127.0.0.1:8001/api/projects?page=1&page_size=10
```

如果返回：

```json
{"detail":"Not authenticated"}
```

说明后端已经正常启动，只是该接口需要登录认证。

---

## 五、启动前端

新开一个 PowerShell，进入前端目录：

```powershell
cd 项目路径\frontend
```

安装依赖：

```powershell
npm install
```

修改前端环境变量文件：

```text
frontend/.env
```

如果后端运行在 8001 端口：

```env
VITE_API_BASE_URL=http://127.0.0.1:8001
VITE_ENABLE_MOCK=false
```

如果后端运行在 8000 端口：

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_ENABLE_MOCK=false
```

注意：修改 `frontend/.env` 后，必须重启前端服务。

启动前端：

```powershell
npm run dev
```

前端默认访问地址：

```text
http://localhost:5173
```

---

## 六、正常测试流程

打开前端页面后，按下面流程测试：

```text
1. 注册或登录账号
2. 新建项目
3. 上传 ZIP 源码包
4. 点击“同步代码”或“解析”
5. 等待解析完成
6. 左侧文件树应能显示源码文件
7. 在右侧 AI 指令框输入需求
8. 选择图表类型，例如流程图、类图、时序图、状态图
9. 点击“生成图表”
10. 中间区域应渲染 Mermaid 图
11. 点击图中的节点，右侧源码面板应显示对应代码
```

---

## 七、判断是否启动成功

如果后端终端看到类似下面的日志：

```text
POST /api/projects/3/parse HTTP/1.1" 200 OK
POST /api/projects/3/analysis HTTP/1.1" 200 OK
GET /api/diagrams/xx HTTP/1.1" 200 OK
```

说明后端解析和图表生成流程成功。

如果前端页面能正常看到：

```text
文件树
Mermaid 图表
源码面板
AI 指令区域
```

说明前后端联调成功。

---

## 八、查看 Agent 是否运行

可以使用数据库可视化软件打开后端 SQLite 数据库，例如：

```text
Navicat Premium Lite
DBeaver
SQLiteStudio
```

打开数据库后，查看表：

```text
agent_runs
```

重点看这些字段：

```text
agent_name
status
model_name
latency_ms
error_message
```

如果没有接入 DeepSeek，可能会看到：

```text
未启用 LLM，沿用规则图
```

如果 DeepSeek 已经启用，最新记录里通常会出现：

```text
model_name = deepseek-chat
```

并且 `DiagramAgent` 的输出不再是“未启用 LLM”。

---

## 九、常见问题

### 1. 端口 8000 被占用

可以改用 8001 启动后端：

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --access-log --log-level debug
```

然后前端 `.env` 也要同步改成：

```env
VITE_API_BASE_URL=http://127.0.0.1:8001
```

---

### 2. 前端请求还是打到旧端口

修改 `frontend/.env` 后，一定要重启前端：

```powershell
Ctrl + C
npm run dev
```

---

### 3. 后端依赖安装失败

先确认 Python 版本：

```powershell
python --version
```

建议使用：

```text
Python 3.11.x
```

如果不是 Python 3.11，建议重新创建虚拟环境。

---

### 4. DeepSeek 没有启用

检查后端 `.env`：

```env
LLM_ENABLED=true
LLM_API_KEY=你的DeepSeek_API_Key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
LLM_MAX_CONTEXT_CHARS=12000
```

修改后需要重启后端。
