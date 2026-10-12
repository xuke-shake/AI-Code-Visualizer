import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'

const projectApi = vi.hoisted(() => ({
  fetchProjectApi: vi.fn(),
  fetchProjectTreeApi: vi.fn(),
  fetchProjectsApi: vi.fn(),
  createProjectApi: vi.fn(),
  deleteProjectApi: vi.fn(),
  updateProjectApi: vi.fn(),
  parseProjectApi: vi.fn(),
  syncProjectApi: vi.fn(),
}))

const diagramApi = vi.hoisted(() => ({
  fetchDiagramApi: vi.fn(),
  generateDiagramApi: vi.fn(),
  saveDiagramApi: vi.fn(),
  shareDiagramApi: vi.fn(),
}))

vi.mock('@/api/project', () => projectApi)
vi.mock('@/api/diagram', () => diagramApi)

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

const project = (id: string) => ({
  id,
  name: `项目-${id}`,
  description: '',
  sourceType: 'zip' as const,
  status: 'ready' as const,
  language: 'Python',
  fileCount: 1,
  updatedAt: '',
  createdAt: '',
})

describe('review follow-ups', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    projectApi.fetchProjectsApi.mockResolvedValue({ list: [], pagination: { page: 1, pageSize: 8, total: 0 } })
  })

  it('keeps B when A finishes after B', async () => {
    const aProject = deferred<ReturnType<typeof project>>()
    const bProject = deferred<ReturnType<typeof project>>()
    const aTree = deferred<never[]>()
    const bTree = deferred<never[]>()
    projectApi.fetchProjectApi.mockImplementation((id: string) => (id === 'A' ? aProject.promise : bProject.promise))
    projectApi.fetchProjectTreeApi.mockImplementation((id: string) => (id === 'A' ? aTree.promise : bTree.promise))

    const { useProjectStore } = await import('./projectStore')
    const store = useProjectStore()
    const requestA = store.selectProject('A')
    const requestB = store.selectProject('B')
    bProject.resolve(project('B'))
    await nextTick()
    bTree.resolve([])
    await requestB
    aProject.resolve(project('A'))
    await nextTick()
    aTree.resolve([])
    await requestA

    expect(store.currentProject?.id).toBe('B')
    expect(store.fileTree).toEqual([])
    expect(store.loading).toBe(false)
  })

  it('keeps a new draft and dirty state when save returns', async () => {
    const initial = { id: 'd1', projectId: '1', title: '图', type: 'flowchart' as const, mermaidCode: 'flowchart TD\nA-->B', version: 1, isOutdated: false, sourceMap: {} }
    const saved = { ...initial, mermaidCode: 'flowchart TD\nA-->C', version: 2 }
    diagramApi.fetchDiagramApi.mockResolvedValue(initial)
    const save = deferred<typeof saved>()
    diagramApi.saveDiagramApi.mockReturnValue(save.promise)

    const { useDiagramStore } = await import('./diagramStore')
    const store = useDiagramStore()
    await store.fetchDiagram('1')
    store.setEditorContent('flowchart TD\nA-->C')
    const saving = store.saveDiagram('1')
    store.setEditorContent('flowchart TD\nA-->D')
    save.resolve(saved)
    await saving

    expect(store.editorContent).toBe('flowchart TD\nA-->D')
    expect(store.currentDiagram?.mermaidCode).toBe('flowchart TD\nA-->C')
    expect(store.dirty).toBe(true)
  })

  it('does not overwrite a new draft when refresh returns', async () => {
    const initial = { id: 'd1', projectId: '1', title: '图', type: 'flowchart' as const, mermaidCode: 'flowchart TD\nA-->B', version: 1, isOutdated: false, sourceMap: {} }
    const refreshed = { ...initial, mermaidCode: 'flowchart TD\nA-->C', version: 2 }
    const fetch = deferred<typeof refreshed>()
    diagramApi.fetchDiagramApi.mockResolvedValueOnce(initial).mockReturnValueOnce(fetch.promise)

    const { useDiagramStore } = await import('./diagramStore')
    const store = useDiagramStore()
    await store.fetchDiagram('1')
    const refreshing = store.refreshDiagram('1')
    store.setEditorContent('flowchart TD\nA-->D')
    fetch.resolve(refreshed)
    await refreshing

    expect(store.editorContent).toBe('flowchart TD\nA-->D')
    expect(store.currentDiagram?.mermaidCode).toBe('flowchart TD\nA-->C')
    expect(store.dirty).toBe(true)
  })

  it('preserves a draft that was already dirty before refresh starts', async () => {
    const initial = { id: 'd1', projectId: '1', title: '图', type: 'flowchart' as const, mermaidCode: 'flowchart TD\nA-->B', version: 1, isOutdated: false, sourceMap: {} }
    diagramApi.fetchDiagramApi.mockResolvedValue(initial)
    const { useDiagramStore } = await import('./diagramStore')
    const store = useDiagramStore()
    await store.fetchDiagram('1')
    store.setEditorContent('flowchart TD\nA-->Draft')
    await store.refreshDiagram('1')
    expect(store.editorContent).toBe('flowchart TD\nA-->Draft')
    expect(store.currentDiagram?.mermaidCode).toBe(initial.mermaidCode)
    expect(store.dirty).toBe(true)
  })

  it.each([true, false])('preserves edits made during generation and recomputes dirty (different=%s)', async (different) => {
    const generated = { id: 'd2', projectId: '1', title: '图', type: 'flowchart' as const, mermaidCode: 'flowchart TD\nA-->Generated', version: 1, isOutdated: false, sourceMap: {} }
    const generation = deferred<typeof generated>()
    diagramApi.generateDiagramApi.mockReturnValue(generation.promise)
    const { useDiagramStore } = await import('./diagramStore')
    const store = useDiagramStore()
    const request = store.generateDiagram('1', { instruction: '按源码生成', type: 'flowchart', selectedPaths: ['a.py'] })
    const draft = different ? 'flowchart TD\nA-->Draft' : generated.mermaidCode
    store.setEditorContent(draft)
    generation.resolve(generated)
    await request
    expect(store.currentDiagram?.id).toBe('d2')
    expect(store.editorContent).toBe(draft)
    expect(store.dirty).toBe(different)
  })
})
