import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { createProjectApi, deleteProjectApi, fetchProjectApi, fetchProjectsApi, fetchProjectTreeApi, parseProjectApi, syncProjectApi, updateProjectApi } from '@/api/project'
import type { CreateProjectPayload, FileTreeNode, Pagination, ProjectItem } from '@/types'

const defaultPagination: Pagination = { page: 1, pageSize: 8, total: 0 }

export const useProjectStore = defineStore('project', () => {
  const projectList = ref<ProjectItem[]>([])
  const pagination = ref<Pagination>({ ...defaultPagination })
  const currentProject = ref<ProjectItem | null>(null)
  const fileTree = ref<FileTreeNode[]>([])
  const loading = ref(false)
  const parsing = ref(false)
  let projectRequestSequence = 0
  let listRequestSequence = 0

  const hasProjects = computed(() => projectList.value.length > 0)

  async function fetchProjects(keyword = '', page = pagination.value.page, pageSize = pagination.value.pageSize): Promise<void> {
    const sequence = ++listRequestSequence
    loading.value = true
    try {
      const result = await fetchProjectsApi({ keyword, page, pageSize })
      if (sequence !== listRequestSequence) return
      projectList.value = result.list
      pagination.value = result.pagination
    } finally {
      if (sequence === listRequestSequence) loading.value = false
    }
  }

  async function createProject(payload: CreateProjectPayload): Promise<ProjectItem> {
    const project = await createProjectApi(payload)
    await fetchProjects()
    return project
  }

  async function updateProject(projectId: string, payload: Partial<ProjectItem>): Promise<void> {
    await updateProjectApi(projectId, payload)
    await fetchProjects()
  }

  async function removeProject(projectId: string): Promise<void> {
    if (currentProject.value?.id === projectId) {
      projectRequestSequence += 1
      currentProject.value = null
      fileTree.value = []
      loading.value = false
    }
    await deleteProjectApi(projectId)
    await fetchProjects()
  }

  async function removeProjects(projectIds: string[]): Promise<void> {
    for (const id of projectIds) {
      if (currentProject.value?.id === id) {
        projectRequestSequence += 1
        currentProject.value = null
        fileTree.value = []
        loading.value = false
      }
      await deleteProjectApi(id)
    }
    await fetchProjects()
  }

  async function selectProject(projectId: string): Promise<void> {
    const sequence = ++projectRequestSequence
    currentProject.value = null
    fileTree.value = []
    parsing.value = false
    loading.value = true
    try {
      const project = await fetchProjectApi(projectId)
      if (sequence !== projectRequestSequence) return
      currentProject.value = project
      await fetchFileTree(projectId, sequence)
    } catch (error) {
      if (sequence === projectRequestSequence) {
        currentProject.value = null
        fileTree.value = []
      }
      throw error
    } finally {
      if (sequence === projectRequestSequence) loading.value = false
    }
  }

  async function fetchFileTree(projectId: string, sequence = projectRequestSequence): Promise<void> {
    const tree = await fetchProjectTreeApi(projectId)
    if (sequence !== projectRequestSequence || currentProject.value?.id !== projectId) return
    fileTree.value = tree
  }

  function pruneSelectedPaths(paths: string[]): string[] {
    const valid = new Set<string>()
    const walk = (nodes: FileTreeNode[]) => nodes.forEach((node) => {
      if (node.type === 'file') valid.add(node.path)
      if (node.children) walk(node.children)
    })
    walk(fileTree.value)
    return paths.filter((path) => valid.has(path))
  }

  async function parseCurrentProject(): Promise<{ taskId: number; status: string; progress: number } | null> {
    if (!currentProject.value) return null
    const projectId = currentProject.value.id
    const sequence = projectRequestSequence
    parsing.value = true
    try {
      const result = await parseProjectApi(projectId)
      if (sequence === projectRequestSequence && currentProject.value?.id === projectId) {
        currentProject.value.status = result.status === 'success' ? 'ready' : result.status === 'failed' ? 'error' : 'parsing'
      }
      return { taskId: result.task_id, status: result.status, progress: result.progress }
    } catch (error) {
      if (sequence === projectRequestSequence && currentProject.value?.id === projectId) currentProject.value.status = 'error'
      throw error
    } finally {
      if (sequence === projectRequestSequence) parsing.value = false
    }
  }

  async function syncCurrentProject(): Promise<{ taskId: number; status: string; progress: number } | null> {
    if (!currentProject.value) return null
    const projectId = currentProject.value.id
    const sequence = projectRequestSequence
    try {
      const result = await syncProjectApi(projectId)
      if (sequence === projectRequestSequence && currentProject.value?.id === projectId) {
        currentProject.value.status = result.status === 'failed' ? 'error' : result.status === 'success' ? 'ready' : 'parsing'
      }
      return { taskId: result.task_id, status: result.status, progress: result.progress }
    } catch (error) {
      if (sequence === projectRequestSequence && currentProject.value?.id === projectId) currentProject.value.status = 'error'
      throw error
    }
  }

  function reset(): void {
    projectRequestSequence += 1
    listRequestSequence += 1
    projectList.value = []
    pagination.value = { ...defaultPagination }
    currentProject.value = null
    fileTree.value = []
    loading.value = false
    parsing.value = false
  }

  return {
    projectList,
    pagination,
    currentProject,
    fileTree,
    loading,
    parsing,
    hasProjects,
    fetchProjects,
    createProject,
    updateProject,
    removeProject,
    removeProjects,
    selectProject,
    fetchFileTree,
    pruneSelectedPaths,
    parseCurrentProject,
    syncCurrentProject,
    reset,
  }
})
