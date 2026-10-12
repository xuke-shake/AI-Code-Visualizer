import { afterEach, describe, expect, it, vi } from 'vitest'

describe('C22: mock synchronous generation contract', () => {
  afterEach(() => { vi.useRealTimers(); vi.unstubAllEnvs(); vi.resetModules(); localStorage.clear() })
  it('resolves only with the newly created requested diagram', async () => {
    vi.resetModules()
    vi.stubEnv('VITE_ENABLE_MOCK', 'true')
    vi.useFakeTimers()
    const { setStoredToken } = await import('@/utils/storage')
    setStoredToken('mock-token-1')
    const { generateDiagramApi, fetchDiagramApi } = await import('@/api/diagram')
    const generation = generateDiagramApi('10', { instruction: '生成时序图', type: 'sequenceDiagram', selectedPaths: ['src/App.vue'] })
    await vi.advanceTimersByTimeAsync(4000)
    const result = await generation
    expect(result.type).toBe('sequenceDiagram')
    expect(result.version).toBe(1)
    const getLatest = fetchDiagramApi('10')
    await vi.advanceTimersByTimeAsync(300)
    const latest = await getLatest
    expect(latest?.id).toBe(result.id)
    expect(latest?.type).toBe('sequenceDiagram')
  })
})
