import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useTaskStore } from './taskStore'
const api = vi.hoisted(() => ({ fetchTaskApi: vi.fn() }))
vi.mock('@/api/project', () => api)
vi.mock('@/utils/config', () => ({ ENABLE_MOCK: false }))

describe('C19: connection and request lifetime', () => {
  beforeEach(() => { setActivePinia(createPinia()); vi.clearAllMocks() })
  it.each(['reset', 'disconnect', 'switch'])('discards a late snapshot after %s', async (change) => {
    let resolve!: (value: unknown) => void
    api.fetchTaskApi.mockReturnValue(new Promise((done) => { resolve = done }))
    const store = useTaskStore()
    store.connect('1')
    const pending = store.loadTask('1', 7, 'sync')
    if (change === 'reset') store.reset()
    else if (change === 'disconnect') store.disconnect()
    else store.connect('2')
    resolve({ id: 7, project_id: 1, status: 'success', progress: 100, message: 'old' })
    await pending
    expect(store.currentTask).toBeNull()
    expect(store.taskHistory).toEqual([])
  })
  it('ignores a late failure after switching', async () => {
    let reject!: (error: unknown) => void
    api.fetchTaskApi.mockReturnValue(new Promise((_, fail) => { reject = fail }))
    const store = useTaskStore()
    store.connect('1')
    const pending = store.loadTask('1', 7, 'sync')
    store.connect('2')
    const before = store.socketStatus
    reject(new Error('old'))
    await pending
    expect(store.socketStatus).toBe(before)
  })
  it('only the latest requested task can fill the current panel', async () => {
    let resolve!: (value: unknown) => void
    api.fetchTaskApi.mockReturnValueOnce(new Promise((done) => { resolve = done })).mockResolvedValueOnce({ id: 8, project_id: 1, status: 'success', progress: 100, message: 'latest' })
    const store = useTaskStore()
    store.connect('1')
    const old = store.loadTask('1', 7, 'parse')
    await store.loadTask('1', 8, 'sync')
    resolve({ id: 7, project_id: 1, status: 'failed', progress: 100, message: 'old' })
    await old
    expect(store.currentTask?.taskId).toBe('8')
  })
})
