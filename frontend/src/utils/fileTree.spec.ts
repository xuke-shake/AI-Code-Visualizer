import { describe, expect, it } from 'vitest'
import { collectLeafPaths } from './fileTree'

describe('collectLeafPaths', () => {
  it('递归收集文件节点路径', () => {
    const result = collectLeafPaths([
      {
        id: '1',
        name: 'src',
        path: 'src',
        type: 'directory',
        children: [
          { id: '2', name: 'App.vue', path: 'src/App.vue', type: 'file' },
          { id: '3', name: 'main.ts', path: 'src/main.ts', type: 'file' },
        ],
      },
    ])

    expect(result).toEqual(['src/App.vue', 'src/main.ts'])
  })
})
