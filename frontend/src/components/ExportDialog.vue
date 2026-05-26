<script setup lang="ts">
import type { ExportType } from '@/types'

defineProps<{
  visible: boolean
  shareUrl: string
}>()

const emit = defineEmits<{
  close: []
  export: [type: ExportType]
  share: []
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
        <button v-for="type in exportTypes" :key="type" class="btn-secondary" @click="emit('export', type)">
          {{ type.toUpperCase() }}
        </button>
      </div>

      <div class="share-box">
        <input :value="shareUrl" readonly placeholder="点击按钮生成分享链接" />
        <button class="btn-primary" @click="emit('share')">生成链接</button>
      </div>
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

.share-box,
.export-grid {
  display: grid;
  gap: 4px;
}

.export-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.share-box {
  grid-template-columns: 1fr auto;
}

@media (max-width: 640px) {
  .share-box,
  .export-grid {
    grid-template-columns: 1fr;
  }
}
</style>
