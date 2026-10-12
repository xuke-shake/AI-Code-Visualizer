import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h, nextTick, watch } from 'vue'
import WorkspaceView from '@/views/WorkspaceView.vue'
import ProjectListView from '@/views/ProjectListView.vue'
import { useUserStore } from '@/stores/userStore'
import { useDiagramStore } from '@/stores/diagramStore'
import { useProjectStore } from '@/stores/projectStore'
import { useTaskStore } from '@/stores/taskStore'

const projectApi = vi.hoisted(() => ({
  fetchProjectsApi: vi.fn(), fetchProjectApi: vi.fn(), fetchProjectTreeApi: vi.fn(),
  createProjectApi: vi.fn(), updateProjectApi: vi.fn(), deleteProjectApi: vi.fn(),
  parseProjectApi: vi.fn(), syncProjectApi: vi.fn(), fetchTaskApi: vi.fn(),
}))
const diagramApi = vi.hoisted(() => ({ fetchDiagramApi: vi.fn(), generateDiagramApi: vi.fn(), saveDiagramApi: vi.fn(), shareDiagramApi: vi.fn() }))
const navigation = vi.hoisted(() => ({ push: vi.fn() }))
vi.mock('@/api/project', () => projectApi)
vi.mock('@/api/diagram', () => diagramApi)
vi.mock('@/api/http', () => ({ setAuthInvalidationHandler: vi.fn(), requestData: vi.fn() }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { projectId: '1' } }), useRouter: () => navigation }))
vi.mock('@/utils/download', () => ({ downloadSvgAsPdf: vi.fn(), downloadSvgAsPng: vi.fn(), downloadText: vi.fn() }))

const project = { id: '1', name: 'Project 1', fileCount: 1, sourceType: 'zip', status: 'ready', diagramCount: 1, createdAt: '', updatedAt: '' }
const original = {
  id: 'd1', projectId: '1', title: 'Original', type: 'flowchart',
  mermaidCode: 'flowchart TD\nA-->B', version: 1, outdated: false, updatedAt: '', sourceMap: {},
  generationMetadata: { generationMode: 'structural_fallback', qualityStatus: 'fallback', reason: 'LLM 未启用' },
}

const CanvasStub = defineComponent({
  props: { code: { type: String, default: '' }, loading: Boolean, renderRequestKey: { type: Number, default: 0 } }, emits: ['pending', 'rendered'],
  setup(props, { emit, expose }) {
    let sequence = 0
    watch(() => [props.code, props.renderRequestKey], async () => {
      await nextTick()
      const event = { requestKey: props.renderRequestKey, code: props.code, sequence: ++sequence }
      emit('pending', { ...event, status: 'pending' })
      if (props.code) emit('rendered', { ...event, status: 'success' })
    }, { immediate: true })
    expose({ rerender: () => emit('rendered', { requestKey: props.renderRequestKey, code: props.code, sequence: ++sequence, status: 'success' }), getSvgElement: () => null })
    return () => h('div', { 'data-canvas': true }, String(props.code))
  },

})

const mounted: Array<{ unmount: () => void }> = []
function workspace() {
  const wrapper = mount(WorkspaceView, { global: { stubs: { MermaidCanvas: CanvasStub } } })
  mounted.push(wrapper)
  return wrapper
}

describe('review: visible workflow evidence', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    projectApi.fetchProjectsApi.mockResolvedValue({ list: [project], pagination: { page: 1, pageSize: 10, total: 1 } })
    projectApi.fetchProjectApi.mockResolvedValue(project)
    projectApi.fetchProjectTreeApi.mockResolvedValue([{ id: 'f1', type: 'file', name: 'a.py', path: 'a.py' }])
    diagramApi.fetchDiagramApi.mockResolvedValue(original)
    useUserStore().hydrate = vi.fn().mockResolvedValue(true)
  })
  afterEach(() => { mounted.splice(0).forEach((wrapper) => wrapper.unmount()) })

  it('C16: failed sync displays failure and the real reason', async () => {
    projectApi.syncProjectApi.mockResolvedValue({ task_id: 7, status: 'failed', progress: 100 })
    projectApi.fetchTaskApi.mockResolvedValue({ id: 7, project_id: 1, task_type: 'sync', status: 'failed', progress: 100, message: 'ZIP 文件不存在', created_at: '' })
    const wrapper = workspace()
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '同步代码')!.trigger('click')
    await flushPromises()
    expect(useProjectStore().currentProject?.status).toBe('error')
    expect(useTaskStore().currentTask?.status).toBe('error')
    expect(wrapper.get('.notice.info').text()).toContain('ZIP 文件不存在')
    expect(wrapper.get('.progress-card').text()).toContain('100%')
    expect(wrapper.get('.progress-card').text()).toContain('执行失败')
  })

  it('C16: successful generation loads its terminal task', async () => {
    diagramApi.generateDiagramApi.mockResolvedValue({ ...original, id: 'd2', analysisTaskId: 8, mermaidCode: 'flowchart TD\nA-->Generated' })
    projectApi.fetchTaskApi.mockResolvedValue({ id: 8, project_id: 1, task_type: 'diagram', status: 'success', progress: 100, message: '图表生成成功', created_at: '' })
    const wrapper = workspace()
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '生成图表')!.trigger('click')
    await flushPromises()
    expect(projectApi.fetchTaskApi).toHaveBeenCalledWith('8')
    expect(useTaskStore().currentTask?.taskId).toBe('8')
    expect(useTaskStore().currentTask?.status).toBe('success')
    expect(wrapper.get('.progress-card').text()).toContain('连接：disconnected')
    expect(wrapper.get('.progress-card').text()).toContain('执行完成')
  })

  it('C19: a snapshot after reset cannot revive an old task', async () => {
    let finish!: (value: unknown) => void
    projectApi.fetchTaskApi.mockReturnValue(new Promise((resolve) => { finish = resolve }))
    const tasks = useTaskStore()
    tasks.connect('1')
    const pending = tasks.loadTask('1', 7, 'sync')
    tasks.reset()
    tasks.connect('2')
    finish({ id: 7, project_id: 1, task_type: 'sync', status: 'success', progress: 100, message: 'A 项目同步完成', created_at: '' })
    await pending
    expect(tasks.currentTask).toBeNull()
    expect(tasks.taskHistory).toEqual([])
  })

  it('C18: save and redraw display edited provenance', async () => {
    const saved = { ...original, mermaidCode: 'flowchart TD\nA-->Edited', version: 2, generationMetadata: { generationMode: 'edited', qualityStatus: null, reason: '编辑后的图表' } }
    diagramApi.saveDiagramApi.mockResolvedValue(saved)
    const wrapper = workspace()
    await flushPromises()
    useDiagramStore().setEditorContent(saved.mermaidCode)
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '保存')!.trigger('click')
    await flushPromises()
    expect(wrapper.get('.notice.info').text()).toContain('编辑后的图表')
    await wrapper.findAll('button').find((button) => button.text() === '重绘')!.trigger('click')
    await flushPromises()
    expect(useDiagramStore().currentDiagram?.generationMetadata?.generationMode).toBe('edited')
    expect(useDiagramStore().generationMetadata?.generationMode).toBe('edited')
    expect(wrapper.get('.notice.info').text()).toContain('编辑后的图表')
  })

  it('C17: parsing permits only one pending request', async () => {
    let finish!: (value: unknown) => void
    projectApi.parseProjectApi.mockReturnValue(new Promise((resolve) => { finish = resolve }))
    const wrapper = mount(ProjectListView)
    mounted.push(wrapper)
    await flushPromises()
    await wrapper.get('.project-checkbox input').trigger('change')
    const parse = wrapper.findAll('button').find((button) => button.text() === '解析')!
    await parse.trigger('click')
    await nextTick()
    expect(parse.attributes('disabled')).toBeDefined()
    for (const label of ['同步', '删除']) expect(wrapper.findAll('button').find((button) => button.text() === label)!.attributes('disabled')).toBeDefined()
    await parse.trigger('click')
    expect(projectApi.parseProjectApi).toHaveBeenCalledTimes(1)
    finish({ task_id: 7, status: 'success', progress: 100 })
    await flushPromises()
    expect(parse.attributes('disabled')).toBeUndefined()
  })
  it('C21: creation has no unsupported description input', async () => {
    const wrapper = mount(ProjectListView)
    mounted.push(wrapper)
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('新建项目'))!.trigger('click')
    expect(wrapper.text()).not.toContain('项目描述')
    expect(wrapper.text()).toContain('已扫描文件')
  })

  it('C17: workspace sync permits only one pending request', async () => {
    let finish!: (value: unknown) => void
    projectApi.syncProjectApi.mockReturnValue(new Promise((resolve) => { finish = resolve }))
    projectApi.fetchTaskApi.mockResolvedValue({ id: 7, project_id: 1, task_type: 'sync', status: 'failed', progress: 100, message: 'ZIP 文件不存在', created_at: '' })
    const wrapper = workspace()
    await flushPromises()
    const sync = wrapper.findAll('button').find((button) => button.text() === '同步代码')!
    await sync.trigger('click')
    expect(sync.attributes('disabled')).toBeDefined()
    await sync.trigger('click')
    expect(projectApi.syncProjectApi).toHaveBeenCalledTimes(1)
    finish({ task_id: 7, status: 'failed', progress: 100 })
    await flushPromises()
    expect(sync.attributes('disabled')).toBeUndefined()
  })

  it('C16: an HTTP generation error loads the failed task snapshot', async () => {
    diagramApi.generateDiagramApi.mockRejectedValue(Object.assign(new Error('服务器内部错误'), { taskId: 9 }))
    projectApi.fetchTaskApi.mockResolvedValue({ id: 9, project_id: 1, task_type: 'diagram', status: 'failed', progress: 100, message: '图表生成失败', created_at: '' })
    const wrapper = workspace()
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '生成图表')!.trigger('click')
    await flushPromises()
    expect(projectApi.fetchTaskApi).toHaveBeenCalledWith('9')
    expect(wrapper.get('.progress-card').text()).toContain('执行失败')
  })
})
