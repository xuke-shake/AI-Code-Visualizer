import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { createProjectApi, deleteProjectApi, fetchProjectsApi, fetchProjectTreeApi, parseProjectApi, syncProjectApi, updateProjectApi } from '@/api/project'
import type { CreateProjectPayload, FileTreeNode, Pagination, ProjectItem } from '@/types'

const defaultPagination: Pagination = { page: 1, pageSize: 8, total: 0 }

export const useProjectStore = defineStore('project', () => {
  const projectList = ref<ProjectItem[]>([])
  const pagination = ref<Pagination>({ ...defaultPagination })
  const currentProject = ref<ProjectItem | null>(null)
  const fileTree = ref<FileTreeNode[]>([])
  const loading = ref(false)
  const parsing = ref(false)

  const hasProjects = computed(() => projectList.value.length > 0)

  async function fetchProjects(keyword = '', page = pagination.value.page, pageSize = pagination.value.pageSize): Promise<void> {
    loading.value = true
    try {
      const result = await fetchProjectsApi({ keyword, page, pageSize })
      projectList.value = result.list
      pagination.value = result.pagination
      if (currentProject.value) {
        currentProject.value = result.list.find((item) => item.id === currentProject.value?.id) ?? currentProject.value
      }
    } finally {
      loading.value = false
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
    await deleteProjectApi(projectId)
    if (currentProject.value?.id === projectId) {
      currentProject.value = null
      fileTree.value = []
    }
  }

  async function removeProjects(projectIds: string[]): Promise<void> {
    for (const id of projectIds) {
      await deleteProjectApi(id)
      if (currentProject.value?.id === id) {
        currentProject.value = null
        fileTree.value = []
      }
    }
    await fetchProjects()
  }

  async function selectProject(projectId: string): Promise<void> {
    if (!projectList.value.length) {
      await fetchProjects()
    }
    currentProject.value = projectList.value.find((item) => item.id === projectId) ?? currentProject.value
    await fetchFileTree(projectId)
  }

  async function fetchFileTree(projectId: string): Promise<void> {
    fileTree.value = await fetchProjectTreeApi(projectId)
  }

  async function parseCurrentProject(): Promise<void> {
    if (!currentProject.value) return
    parsing.value = true
    try {
      await parseProjectApi(currentProject.value.id)
      currentProject.value.status = 'parsing'
    } finally {
      parsing.value = false
    }
  }

  async function syncCurrentProject(): Promise<void> {
    if (!currentProject.value) return
    await syncProjectApi(currentProject.value.id)
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
    parseCurrentProject,
    syncCurrentProject,
  }
})
