import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { exportDiagramApi, fetchDiagramApi, generateDiagramApi, saveDiagramApi, shareDiagramApi } from '@/api/diagram'
import type { DiagramDetail, ExportType, GenerateDiagramPayload } from '@/types'

export const useDiagramStore = defineStore('diagram', () => {
  const currentDiagram = ref<DiagramDetail | null>(null)
  const editorContent = ref('')
  const selectedNode = ref('')
  const shareUrl = ref('')
  const loading = ref(false)

  const selectedSource = computed(() => currentDiagram.value?.sourceMap?.[selectedNode.value] ?? null)

  async function fetchDiagram(projectId: string): Promise<void> {
    loading.value = true
    try {
      const data = await fetchDiagramApi(projectId)
      currentDiagram.value = data
      editorContent.value = data?.mermaidCode ?? ''
      shareUrl.value = data?.shareUrl ?? ''
    } finally {
      loading.value = false
    }
  }

  async function generateDiagram(projectId: string, payload: GenerateDiagramPayload): Promise<void> {
    loading.value = true
    try {
      const data = await generateDiagramApi(projectId, payload)
      currentDiagram.value = data
      editorContent.value = data.mermaidCode
      shareUrl.value = data.shareUrl ?? ''
    } finally {
      loading.value = false
    }
  }

  async function refreshDiagram(projectId: string): Promise<void> {
    await fetchDiagram(projectId)
  }

  async function saveDiagram(projectId: string): Promise<void> {
    if (!currentDiagram.value) return
    const saved = await saveDiagramApi(projectId, currentDiagram.value.id, {
      mermaidCode: editorContent.value,
      type: currentDiagram.value.type,
    })
    currentDiagram.value = saved
    editorContent.value = saved.mermaidCode
  }

  function setEditorContent(value: string): void {
    editorContent.value = value
  }

  function selectNode(label: string): void {
    selectedNode.value = label.trim()
  }

  async function share(projectId: string): Promise<string> {
    if (!currentDiagram.value) return ''
    const result = await shareDiagramApi(projectId, currentDiagram.value.id)
    shareUrl.value = result.shareUrl
    return result.shareUrl
  }

  async function exportMermaid(projectId: string, type: ExportType): Promise<void> {
    if (!currentDiagram.value) return
    await exportDiagramApi(projectId, currentDiagram.value.id, type)
  }

  return {
    currentDiagram,
    editorContent,
    selectedNode,
    selectedSource,
    shareUrl,
    loading,
    fetchDiagram,
    generateDiagram,
    refreshDiagram,
    saveDiagram,
    setEditorContent,
    selectNode,
    share,
    exportMermaid,
  }
})
