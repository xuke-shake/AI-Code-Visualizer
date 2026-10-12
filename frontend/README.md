# AI-Code-Visualizer 前端

前端使用 Vue 3、TypeScript、Vite 和 Pinia，提供登录、项目列表、源码文件树、图表工作区、Mermaid 编辑及导出界面。

在本目录首次运行：

```powershell
npm ci
Copy-Item .env.example .env
npm run dev
```

默认访问 `http://localhost:5173`。示例配置连接 `http://127.0.0.1:8000`，并关闭 Mock；修改地址后需重启开发服务。已有 `.env` 时保留自己的配置。

检查命令：

```powershell
npm test
npm run check
npm run lint
npm run build
```

`package-lock.json` 用于保持安装版本一致，应和 `package.json` 一起提交。`node_modules/`、`dist/`、类型检查缓存和真实 `.env` 不提交。源码中的 Mock 用于开发和回归测试，保留该文件不会自动开启 Mock。

完整启动和功能边界见 [项目启动说明](../README.md)。接口以运行中的后端 `/docs` 为准。
