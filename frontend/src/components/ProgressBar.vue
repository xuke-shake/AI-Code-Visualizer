<script setup lang="ts">
import { computed } from 'vue'
import type { SocketStatus, TaskProgressEvent } from '@/types'
import { toPercent } from '@/utils/format'

const props = defineProps<{
  task: TaskProgressEvent | null
  history: TaskProgressEvent[]
  socketStatus: SocketStatus
}>()

const percent = computed(() => props.task?.progress ?? 0)
</script>

<template>
  <section class="page-card progress-card">
    <div class="progress-header app-panel-title">
      <div>
        <h3 class="section-title">任务进度</h3>
        <p class="muted">连接：{{ socketStatus }}</p>
      </div>
      <strong>{{ toPercent(percent) }}</strong>
    </div>

    <div class="track">
      <div class="bar" :style="{ width: toPercent(percent) }" />
    </div>

    <div class="timeline">
      <article v-for="item in history.slice(0, 3)" :key="`${item.taskId}-${item.updatedAt}`">
        <span class="badge">{{ item.type }}</span>
        <span class="message">{{ item.message }}</span>
        <strong>{{ item.progress }}%</strong>
      </article>
    </div>
  </section>
</template>

<style scoped>
.progress-card {
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  background: var(--bg-sidebar);
  height: 100%;
}

.progress-header p {
  margin: 1px 0 0;
  font-size: 10px;
}

.track {
  width: 100%;
  height: 4px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 999px;
  overflow: hidden;
}

.bar {
  height: 100%;
  background: linear-gradient(90deg, var(--primary), #3ea6ff);
}

.timeline {
  flex: 1;
  overflow-y: auto;
  display: grid;
  gap: 4px;
}

.timeline article {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 4px;
  align-items: center;
  padding: 4px 6px;
  border-radius: var(--radius-sm);
  background: var(--panel-muted);
}

.message {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
}
</style>
