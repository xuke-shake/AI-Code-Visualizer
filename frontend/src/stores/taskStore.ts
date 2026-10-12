import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { SocketStatus, TaskProgressEvent } from '@/types'
import { createTaskStream } from '@/api/mock'
import { fetchTaskApi } from '@/api/project'
import { ENABLE_MOCK } from '@/utils/config'

export const useTaskStore = defineStore('task', () => {
  let unsubscribe: null | (() => void) = null
  let activeProjectId: string | null = null
  let connectionRevision = 0
  let snapshotSequence = 0
  const currentTask = ref<TaskProgressEvent | null>(null)
  const taskHistory = ref<TaskProgressEvent[]>([])
  const socketStatus = ref<SocketStatus>('idle')

  function connect(projectId: string): void {
    disconnect()
    activeProjectId = projectId
    const revision = connectionRevision
    socketStatus.value = 'connecting'

    if (ENABLE_MOCK) {
      unsubscribe = createTaskStream(
        projectId,
        (payload) => {
          if (revision !== connectionRevision || activeProjectId !== projectId || payload.projectId !== projectId) return
          currentTask.value = payload
          taskHistory.value = [payload, ...taskHistory.value].slice(0, 12)
        },
        (status) => {
          if (revision !== connectionRevision || activeProjectId !== projectId) return
          socketStatus.value = status as SocketStatus
        },
      )
      return
    }

    // 真实后端当前按请求同步执行，/api/tasks/{id}/events 只是一次 SSE
    // 快照；不再连接会发送 task_id=999 的假 WebSocket。
    void projectId
    socketStatus.value = 'disconnected'
    unsubscribe = null
  }

  function disconnect(): void {
    connectionRevision += 1
    snapshotSequence += 1
    activeProjectId = null
    unsubscribe?.()
    unsubscribe = null
    socketStatus.value = 'disconnected'
  }

  function record(projectId: string, taskId: number, type: TaskProgressEvent['type'], status: string, progress: number, message: string, diagnostics: TaskProgressEvent['diagnostics'] = []): void {
    if (activeProjectId !== projectId) return
    const normalized: TaskProgressEvent = {
      projectId,
      taskId: String(taskId),
      type,
      progress,
      status: status === 'failed' ? 'error' : status === 'success' ? 'success' : status === 'pending' ? 'pending' : 'running',
      message,
      updatedAt: new Date().toISOString(),
      diagnostics,
    }
    currentTask.value = normalized
    taskHistory.value = [normalized, ...taskHistory.value.filter((item) => item.taskId !== normalized.taskId)].slice(0, 12)
  }

  async function loadTask(projectId: string, taskId: number, type: TaskProgressEvent['type']): Promise<void> {
    if (ENABLE_MOCK) return
    const revision = connectionRevision
    const sequence = ++snapshotSequence
    const isCurrent = () => revision === connectionRevision && activeProjectId === projectId && sequence === snapshotSequence
    try {
      const task = await fetchTaskApi(String(taskId))
      if (!isCurrent() || projectId !== task.project_id.toString() || task.id !== taskId) return
      record(projectId, task.id, type, task.status, task.progress, task.message || '', task.result_json?.diagnostics ?? [])
    } catch {
      if (isCurrent()) socketStatus.value = 'error'
    }
  }

  function reset(): void {
    disconnect()
    currentTask.value = null
    taskHistory.value = []
    socketStatus.value = 'idle'
  }

  return {
    currentTask,
    taskHistory,
    socketStatus,
    connect,
    record,
    loadTask,
    disconnect,
    reset,
  }
})
