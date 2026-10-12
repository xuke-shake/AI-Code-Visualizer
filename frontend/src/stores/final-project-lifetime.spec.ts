import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useProjectStore } from './projectStore'

const api = vi.hoisted(() => ({
  createProjectApi: vi.fn(), deleteProjectApi: vi.fn(), fetchProjectApi: vi.fn(),
  fetchProjectsApi: vi.fn(), fetchProjectTreeApi: vi.fn(), parseProjectApi: vi.fn(),
  syncProjectApi: vi.fn(), updateProjectApi: vi.fn(),
}))
vi.mock('@/api/project', () => api)
const project = { id: '1', name: 'same', fileCount: 1, sourceType: 'zip', status: 'ready', diagramCount: 0, createdAt: '', updatedAt: '' }

describe('C19: parse request lifetime', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    api.fetchProjectApi.mockImplementation(async () => ({ ...project }))
    api.fetchProjectTreeApi.mockResolvedValue([])
  })
  it.each(['result', 'error'])('ignores an old %s after reset and reselecting the same project', async (outcome) => {
    let finish!: (value: unknown) => void
    let fail!: (value: unknown) => void
    api.parseProjectApi.mockReturnValueOnce(new Promise((resolve, reject) => { finish = resolve; fail = reject }))
    const store = useProjectStore()
    await store.selectProject('1')
    const pending = store.parseCurrentProject().catch(() => null)
    store.reset()
    await store.selectProject('1')
    if (outcome === 'result') finish({ task_id: 7, status: 'failed', progress: 100 })
    else fail(new Error('obsolete failure'))
    await pending
    expect(store.currentProject?.status).toBe('ready')
    expect(store.parsing).toBe(false)
  })
})
