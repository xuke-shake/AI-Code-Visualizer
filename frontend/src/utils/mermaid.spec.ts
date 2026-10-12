import { describe, expect, it } from 'vitest'
import { MERMAID_RENDER_CONFIG, sanitizeMermaidCode } from './mermaid'

describe('Mermaid 安全策略', () => {
  it('使用 strict 且关闭自动执行', () => {
    expect(MERMAID_RENDER_CONFIG.securityLevel).toBe('strict')
    expect(MERMAID_RENDER_CONFIG.startOnLoad).toBe(false)
    expect(MERMAID_RENDER_CONFIG.flowchart.htmlLabels).toBe(false)
    expect(MERMAID_RENDER_CONFIG.htmlLabels).toBe(false)
    expect(MERMAID_RENDER_CONFIG.maxTextSize).toBe(50000)
    expect(MERMAID_RENDER_CONFIG.maxEdges).toBe(500)
  })

  it.each([
    '%%{init: {"securityLevel": "loose"}}%%\nflowchart TD\nA-->B',
    'flowchart TD\nclick A "https://example.com"',
    'flowchart TD\nA["javascript:alert(1)"]',
    'flowchart TD\nA["<script>alert(1)</script>"]',
  ])('拒绝不可信配置、链接和脚本：%s', (code) => {
    expect(() => sanitizeMermaidCode(code)).toThrow('被禁止')
  })

  it('保留普通四类图表源码', () => {
    for (const code of [
      'flowchart TD\nA-->B',
      'sequenceDiagram\nA->>B: hello',
      'stateDiagram-v2\n[*] --> Ready',
      'classDiagram\nclass User',
    ]) {
      expect(sanitizeMermaidCode(code)).toBe(code)
    }
  })

  it('拒绝超过默认文本上限的源码', () => {
    expect(() => sanitizeMermaidCode('flowchart TD\n' + 'A-->B\n'.repeat(10000))).toThrow('50000')
  })
})
