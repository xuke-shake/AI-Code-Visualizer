import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createProjectApi } from './project'
const requestData = vi.hoisted(() => vi.fn())
vi.mock('@/api/http', () => ({ requestData }))
describe('C21: supported project fields', () => {
  beforeEach(() => requestData.mockReset())
  it('returns file count without inventing a project description', async () => {
    requestData.mockResolvedValue({ project: { id: 1, owner_id: 1, name: 'Project', source_type: 'git', status: 'created', file_count: 3, created_at: '', updated_at: '' }, task_id: null })
    const result = await createProjectApi({ name: 'Project', sourceType: 'git', repoUrl: 'https://github.com/example/repo' })
    expect(result.fileCount).toBe(3)
    expect('description' in result).toBe(false)
    expect(requestData.mock.calls[0][0].data.description).toBeUndefined()
  })
})
