import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { SocketStatus, TaskProgressEvent } from '@/types'
import { createTaskStream } from '@/api/mock'

let unsubscribe: null | (() => void) = null

export const useTaskStore = defineStore('task', () => {
  const currentTask = ref<TaskProgressEvent | null>(null)
  const taskHistory = ref<TaskProgressEvent[]>([])
  const socketStatus = ref<SocketStatus>('idle')

  function connect(projectId: string): void {
    unsubscribe?.()
    socketStatus.value = 'connecting'

    if (import.meta.env.VITE_ENABLE_MOCK !== 'false') {
      unsubscribe = createTaskStream(
        projectId,
        (payload) => {
          currentTask.value = payload
          taskHistory.value = [payload, ...taskHistory.value].slice(0, 12)
        },
        (status) => {
          socketStatus.value = status as SocketStatus
        },
      )
      return
    }

    const wsBase = import.meta.env.VITE_WS_BASE_URL || 'ws://localhost:8080/ws'
    const socket = new WebSocket(`${wsBase}/tasks?projectId=${projectId}`)
    socket.onopen = () => {
      socketStatus.value = 'connected'
    }
    socket.onclose = () => {
      socketStatus.value = 'disconnected'
    }
    socket.onerror = () => {
      socketStatus.value = 'error'
    }
    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data) as TaskProgressEvent
      currentTask.value = payload
      taskHistory.value = [payload, ...taskHistory.value].slice(0, 12)
    }

    unsubscribe = () => socket.close()
  }

  function disconnect(): void {
    unsubscribe?.()
    unsubscribe = null
    socketStatus.value = 'disconnected'
  }

  return {
    currentTask,
    taskHistory,
    socketStatus,
    connect,
    disconnect,
  }
})
