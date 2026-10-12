import { describe, expect, it } from 'vitest'
import { sanitizeMermaidCode } from './mermaid'

describe('C20: consistent declaration and config gate', () => {
  it.each(['---\nconfig:\n  htmlLabels: true\n---\nflowchart TD\nA-->B', '---\r\nconfig:\r\n  htmlLabels: true\r\n---\r\nflowchart TD\r\nA-->B'])('rejects YAML config before rendering', (code) => {
    expect(() => sanitizeMermaidCode(code)).toThrow()
  })
  it('rejects undeclared content', () => {
    expect(() => sanitizeMermaidCode('A-->B')).toThrow()
  })
  it.each(['flowchart TD\nA-->B', 'sequenceDiagram\nA->>B:hi', 'stateDiagram-v2\n[*]-->A', 'classDiagram\nclass A'])('keeps valid default diagram text', (code) => {
    expect(sanitizeMermaidCode(code)).toBe(code)
  })
})
