<script setup lang="ts">
import { computed } from 'vue'
import type { DiagramNodeSource } from '@/types'

const props = defineProps<{
  selectedLabel: string
  source: DiagramNodeSource | null
}>()

const lines = computed(() => props.source?.code.split('\n') ?? [])
</script>

<template>
  <section class="page-card source-panel">
    <div class="app-panel-title">
      <div>
        <h3 class="section-title">源码</h3>
        <p class="muted">{{ selectedLabel ? `节点：${selectedLabel}` : '点击图表节点查看源码' }}</p>
      </div>
    </div>

    <div v-if="source" class="source-meta">
      <span class="badge">{{ source.filePath }}</span>
      <span class="badge">{{ source.startLine }} - {{ source.endLine }}</span>
    </div>

    <div v-if="source" class="code-block">
      <div v-for="(line, index) in lines" :key="`${index}-${line}`" class="code-line">
        <span>{{ source.startLine + index }}</span>
        <code>{{ line }}</code>
      </div>
    </div>

    <div v-else class="empty-hint">暂无源码定位信息</div>
  </section>
</template>

<style scoped>
.source-panel {
  padding: 6px;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 4px;
  height: 100%;
  background: var(--bg-sidebar);
}

.source-panel p {
  margin: 1px 0 0;
  font-size: 10px;
}

.source-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.code-block {
  min-height: 0;
  overflow: auto;
  border-radius: var(--radius-sm);
  background: var(--bg-sidebar);
  border: 1px solid rgba(255, 255, 255, 0.04);
}

.code-line {
  display: grid;
  grid-template-columns: 32px 1fr;
  gap: 6px;
  padding: 4px 6px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.03);
  font-size: 11px;
}

.code-line span {
  color: var(--muted);
}

code {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: Consolas, 'Courier New', monospace;
}

.empty-hint {
  display: grid;
  place-items: center;
  min-height: 100px;
  border-radius: var(--radius-sm);
  border: 1px dashed rgba(255, 255, 255, 0.08);
  color: var(--muted);
  font-size: 11px;
}
</style>
