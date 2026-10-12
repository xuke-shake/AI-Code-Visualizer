import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { fetchDiagramApi, generateDiagramApi, saveDiagramApi, shareDiagramApi } from '@/api/diagram'
import type { DiagramDetail, ExportType, GenerateDiagramPayload } from '@/types'

export const useDiagramStore = defineStore('diagram', () => {
  const currentDiagram = ref<DiagramDetail | null>(null)
  const editorContent = ref('')
  const selectedNode = ref('')
  const shareUrl = ref('')
  const loading = ref(false)
  const error = ref('')
  const dirty = ref(false)
  const generationMetadata = ref(null as DiagramDetail['generationMetadata'] | null)
  const savedBaseline = ref('')
  const activeProjectId = ref<string | null>(null)
  let requestSequence = 0
  let editorRevision = 0

  const selectedSource = computed(() => currentDiagram.value?.sourceMap?.[selectedNode.value] ?? null)

  function isCurrent(projectId: string, sequence: number): boolean {
    return activeProjectId.value === projectId && requestSequence === sequence
  }

  function resetForProject(projectId: string): void {
    requestSequence += 1
    activeProjectId.value = projectId
    currentDiagram.value = null
    editorContent.value = ''
    selectedNode.value = ''
    shareUrl.value = ''
    error.value = ''
    dirty.value = false
    generationMetadata.value = null
    savedBaseline.value = ''
    loading.value = false
    editorRevision = 0
  }

  function dispose(): void {
    requestSequence += 1
    activeProjectId.value = null
    currentDiagram.value = null
    editorContent.value = ''
    selectedNode.value = ''
    shareUrl.value = ''
    error.value = ''
    dirty.value = false
    generationMetadata.value = null
    savedBaseline.value = ''
    loading.value = false
    editorRevision = 0
  }

  function reset(): void {
    dispose()
  }

  async function fetchDiagram(projectId: string): Promise<void> {
    if (activeProjectId.value !== projectId) resetForProject(projectId)
    const sequence = ++requestSequence
    const revisionAtRequest = editorRevision
    const dirtyAtRequest = dirty.value
    loading.value = true
    error.value = ''
    try {
      const data = await fetchDiagramApi(projectId)
      if (!isCurrent(projectId, sequence)) return
      const replacingDirtyIdentity = Boolean(dirty.value && currentDiagram.value && data && currentDiagram.value.id !== data.id)
      if (replacingDirtyIdentity) return
      currentDiagram.value = data
      generationMetadata.value = data?.generationMetadata ?? null
      savedBaseline.value = data?.mermaidCode ?? ''
      if (!dirtyAtRequest && editorRevision === revisionAtRequest) editorContent.value = savedBaseline.value
      shareUrl.value = data?.shareUrl ?? ''
      selectedNode.value = ''
      dirty.value = editorContent.value !== savedBaseline.value
    } catch (cause) {
      if (isCurrent(projectId, sequence)) error.value = cause instanceof Error ? cause.message : '图表加载失败'
      throw cause
    } finally {
      if (isCurrent(projectId, sequence)) loading.value = false
    }
  }

  async function generateDiagram(projectId: string, payload: GenerateDiagramPayload): Promise<void> {
    if (activeProjectId.value !== projectId) resetForProject(projectId)
    if (dirty.value) {
      const failure = new Error('当前图表有未保存编辑，请先保存或刷新后再生成')
      error.value = failure.message
      throw failure
    }
    const sequence = ++requestSequence
    const revisionAtRequest = editorRevision
    loading.value = true
    error.value = ''
    try {
      const data = await generateDiagramApi(projectId, payload)
      if (!isCurrent(projectId, sequence)) return
      if (editorRevision !== revisionAtRequest && currentDiagram.value) {
        error.value = '生成结果已返回，但当前仍保留请求前图表的新草稿'
        return
      }
      currentDiagram.value = data
      generationMetadata.value = data.generationMetadata ?? null
      savedBaseline.value = data.mermaidCode
      if (editorRevision === revisionAtRequest) {
        editorContent.value = data.mermaidCode
        dirty.value = false
      } else {
        dirty.value = editorContent.value !== data.mermaidCode
      }
      shareUrl.value = data.shareUrl ?? ''
      selectedNode.value = ''
    } catch (cause) {
      if (isCurrent(projectId, sequence)) error.value = cause instanceof Error ? cause.message : '图表生成失败'
      throw cause
    } finally {
      if (isCurrent(projectId, sequence)) loading.value = false
    }
  }

  async function refreshDiagram(projectId: string): Promise<void> {
    await fetchDiagram(projectId)
  }

  async function saveDiagram(projectId: string): Promise<void> {
    if (!currentDiagram.value || activeProjectId.value !== projectId) {
      const failure = new Error('当前项目没有可保存的图表')
      error.value = failure.message
      throw failure
    }
    const diagramId = currentDiagram.value.id
    const sequence = ++requestSequence
    const revisionAtRequest = editorRevision
    const contentAtRequest = editorContent.value
    loading.value = true
    error.value = ''
    try {
      const saved = await saveDiagramApi(projectId, diagramId, { mermaidCode: contentAtRequest, type: currentDiagram.value.type })
      if (!isCurrent(projectId, sequence) || currentDiagram.value?.id !== diagramId) return
      currentDiagram.value = saved
      generationMetadata.value = saved.generationMetadata ?? null
      savedBaseline.value = saved.mermaidCode
      if (editorRevision === revisionAtRequest) editorContent.value = saved.mermaidCode
      shareUrl.value = saved.shareUrl ?? ''
      dirty.value = editorContent.value !== savedBaseline.value
      if (editorRevision === revisionAtRequest && contentAtRequest !== saved.mermaidCode) {
        dirty.value = true
      }
    } catch (cause) {
      if (isCurrent(projectId, sequence)) error.value = cause instanceof Error ? cause.message : '图表保存失败'
      throw cause
    } finally {
      if (isCurrent(projectId, sequence)) loading.value = false
    }
  }

  function setEditorContent(value: string): void {
    editorRevision += 1
    editorContent.value = value
    dirty.value = value !== savedBaseline.value
  }

  function selectNode(label: string): void {
    selectedNode.value = label.trim()
  }

  async function share(projectId: string): Promise<string> {
    if (!currentDiagram.value || activeProjectId.value !== projectId) return ''
    const sequence = ++requestSequence
    error.value = ''
    try {
      const result = await shareDiagramApi(projectId, currentDiagram.value.id)
      if (!isCurrent(projectId, sequence)) return ''
      shareUrl.value = result.shareUrl
      return result.shareUrl
    } catch (cause) {
      if (isCurrent(projectId, sequence)) error.value = cause instanceof Error ? cause.message : '分享失败'
      throw cause
    }
  }

  async function exportMermaid(projectId: string, type: ExportType): Promise<void> {
    if (!currentDiagram.value || activeProjectId.value !== projectId) return
    // 导出只消费当前已成功渲染的画布；不再依赖后端占位 export 接口。
    if (!['svg', 'png', 'pdf', 'markdown'].includes(type)) {
      throw new Error(`不支持的导出格式：${type}`)
    }
  }

  return { currentDiagram, editorContent, selectedNode, selectedSource, shareUrl, loading, error, dirty, generationMetadata, activeProjectId, resetForProject, dispose, reset, fetchDiagram, generateDiagram, refreshDiagram, saveDiagram, setEditorContent, selectNode, share, exportMermaid }
})
