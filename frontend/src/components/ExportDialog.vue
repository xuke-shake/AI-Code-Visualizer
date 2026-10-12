<script setup lang="ts">
import type { ExportType } from '@/types'

defineProps<{
  visible: boolean
  imageExportDisabled?: boolean
}>()

const emit = defineEmits<{
  close: []
  export: [type: ExportType]
}>()

const exportTypes: ExportType[] = ['svg', 'png', 'pdf', 'markdown']
</script>

<template>
  <div v-if="visible" class="dialog-mask" @click.self="emit('close')">
    <section class="page-card dialog-panel">
      <div class="dialog-header app-panel-title">
        <div>
          <h3 class="section-title">导出与分享</h3>
          <p class="muted">SVG / PNG / PDF / Markdown</p>
        </div>
        <button class="btn-secondary" @click="emit('close')">关闭</button>
      </div>

      <div class="export-grid">
        <button
          v-for="type in exportTypes"
          :key="type"
          class="btn-secondary"
          :disabled="type !== 'markdown' && imageExportDisabled"
          @click="emit('export', type)"
        >
          {{ type.toUpperCase() }}
        </button>
      </div>

      <p class="muted share-disabled">分享链接暂未提供读取页面，当前不支持公开分享。</p>
    </section>
  </div>
</template>

<style scoped>
.dialog-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: grid;
  place-items: center;
  padding: 8px;
  z-index: 30;
}

.dialog-panel {
  width: min(380px, 100%);
  padding: 8px;
  display: grid;
  gap: 6px;
}

.dialog-header p {
  margin: 1px 0 0;
  font-size: 10px;
}

.export-grid {
  display: grid;
  gap: 4px;
}

.export-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

@media (max-width: 640px) {
.export-grid {
    grid-template-columns: 1fr;
  }
}
</style>
