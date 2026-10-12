import mermaid from 'mermaid'

let initialized = false

export const MERMAID_RENDER_CONFIG = {
  startOnLoad: false,
  theme: 'base',
  securityLevel: 'strict' as const,
  htmlLabels: false,
  maxTextSize: 50000,
  maxEdges: 500,
  flowchart: { htmlLabels: false, useMaxWidth: true },
  sequence: { useMaxWidth: true },
  themeVariables: {
    primaryColor: '#e1f5fe',
    primaryTextColor: '#1f2328',
    primaryBorderColor: '#0969da',
    lineColor: '#57606a',
    secondaryColor: '#f6f8fa',
    tertiaryColor: '#ffffff',
    background: '#ffffff',
    mainBkg: '#f6f8fa',
    clusterBkg: '#f6f8fa',
  },
} as const

const UNSAFE_MERMAID_PATTERNS = [
  /%%\s*\{/i,
  /^\s*click(?:\s|$)/i,
  /\bjavascript\s*:/i,
  /\bdata\s*:\s*(?:text\/html|text\/javascript|application\/javascript|application\/x-javascript|image\/svg\+xml)/i,
  /\bhref\s*=/i,
  /<\s*script\b/i,
]

/** 拒绝图内配置、任意链接和回调，不静默改写不可信 Mermaid。 */
export function sanitizeMermaidCode(code: string): string {
  const source = String(code || '').trim()
  if (!source) return ''
  if (source.length > 50000) throw new Error('Mermaid 源码超过 50000 字符限制')
  if (/^---\s*(?:\r?\n|$)/.test(source)) throw new Error('Mermaid 内容包含被禁止的图内配置')

  const unsafeLine = source.split(/\r\n?|\n/).find((line) =>
    UNSAFE_MERMAID_PATTERNS.some((pattern) => pattern.test(line)),
  )
  if (unsafeLine || /%%\s*\}/i.test(source)) {
    throw new Error('Mermaid 内容包含被禁止的安全配置、链接或回调')
  }
  const declaration = source.split(/\s+/)[0]
  if (!['flowchart', 'graph', 'sequenceDiagram', 'stateDiagram', 'stateDiagram-v2', 'classDiagram'].includes(declaration)) {
    throw new Error('缺少合法的 Mermaid 图表声明')
  }

  return source
}

export function ensureMermaid(): typeof mermaid {
  if (!initialized) {
    mermaid.initialize(MERMAID_RENDER_CONFIG)
    initialized = true
  }

  return mermaid
}
