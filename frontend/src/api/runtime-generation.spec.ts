import { beforeEach, describe, expect, it, vi } from 'vitest'
import { generateDiagramApi } from './diagram'
import { createProjectApi, parseProjectApi, syncProjectApi } from './project'

const requestData = vi.hoisted(() => vi.fn())
vi.mock('./http', () => ({ requestData }))

describe('第一学期运行时接口契约', () => {
  beforeEach(() => requestData.mockReset())
  it('长操作使用 180000ms 且不重复发送 scope', async () => {
    requestData
      .mockResolvedValueOnce({ task_id: 1, status: 'success', diagram_id: 2 })
      .mockResolvedValueOnce({ id: 2, project_id: 1, creator_id: 1, title: '图', diagram_type: 'flowchart', mermaid_code: 'flowchart TD\nA-->B', version: 1, is_outdated: false, created_at: '' })
    await generateDiagramApi('1', { instruction: '生成', type: 'flowchart', selectedPaths: ['x'.repeat(9000)] })
    expect(requestData.mock.calls[0][0]).toMatchObject({ timeout: 180000 })
    expect(requestData.mock.calls[0][0].data.scope).toBeUndefined()
    expect(requestData.mock.calls[0][0].data.parameters.selectedPaths[0]).toHaveLength(9000)
  })

  it('解析和同步也使用长操作超时', async () => {
    requestData.mockResolvedValue({ task_id: 1, status: 'pending', progress: 0 })
    await parseProjectApi('1')
    await syncProjectApi('1')
    expect(requestData.mock.calls.at(-2)?.[0]).toMatchObject({ timeout: 180000 })
    expect(requestData.mock.calls.at(-1)?.[0]).toMatchObject({ timeout: 180000 })
  })

  it('项目创建上传链路保留长操作超时', async () => {
    const file = new File(['zip'], 'demo.zip', { type: 'application/zip' })
    requestData.mockResolvedValueOnce({ upload_id: 3 }).mockResolvedValueOnce({ project: { id: 1, owner_id: 1, name: 'p', source_type: 'zip', status: 'created', file_count: 0, created_at: '', updated_at: '' }, task_id: null })
    await createProjectApi({ name: 'p', sourceType: 'zip', zipFile: file })
    expect(requestData.mock.calls[0][0]).toMatchObject({ timeout: 180000 })
    expect(requestData.mock.calls[1][0]).toMatchObject({ timeout: 180000 })
  })
})
