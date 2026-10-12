# 第一学期结构图验收样例

这是静态源码结构样例，不是可部署的登录服务。上传、解析、分析不会执行这份代码。LLM off 时验收源码结构、四图渲染、编辑来源、任务终态和导出，不以它判断业务图准确性。

Windows 在本目录执行：

```powershell
$demoZip = Join-Path $env:TEMP ('semester-demo-' + [guid]::NewGuid().ToString('N') + '.zip')
Compress-Archive -LiteralPath .\main.py,.\auth.py,.\README.md -DestinationPath $demoZip
$demoZip
```

登录 → 新建 ZIP 项目 → 上传 → 全量解析 → 进入工作台 → 选择 main.py 和 auth.py → 输入“分析 target，展示源码中可以确认的结构” → 依次生成流程图、时序图、状态图、架构类图。

静态关系应包含 main.py 对 auth.py 的导入；限定名为 Outer、Outer.Inner、Outer.Inner.run、Outer.outer。类图中 run 属于 Inner，outer 属于 Outer。四类图均应成功渲染；规则降级提示应明确显示。导出 SVG、PNG、PDF、Markdown 后检查实际文件。

编辑 Mermaid 并成功渲染后保存，来源应变为 edited，旧源码映射清除。有效合同下同源码重解析/同步不会使图过期。YAML 图内配置应被拒绝，并禁用图片导出与保存。失败任务即使进度 100%，也应显示失败及原因。
