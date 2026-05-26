import mermaid from 'mermaid'

let initialized = false

export function ensureMermaid(): typeof mermaid {
  if (!initialized) {
    mermaid.initialize({
      startOnLoad: false,
      theme: 'base',
      securityLevel: 'loose',
      themeVariables: {
        primaryColor: '#e1f5fe',      // 浅蓝节点背景
          primaryTextColor: '#1f2328',  // 深色文字
          primaryBorderColor: '#0969da', // 蓝色边框
          lineColor: '#57606a',         // 灰色连线
          secondaryColor: '#f6f8fa',    // 浅灰节点
          tertiaryColor: '#ffffff',     // 白色节点
          background: '#ffffff',        // 白色画布背景（关键）
          mainBkg: '#f6f8fa',           // 浅灰主背景
          clusterBkg: '#f6f8fa',        // 浅灰集群背景
      },
    })
    initialized = true
  }

  return mermaid
}
