<script setup lang="ts">
import { computed } from 'vue'
import FileTreeNode from './FileTreeNode.vue'
import type { FileTreeNode as TreeNode } from '@/types'
import { collectLeafPaths } from '@/utils/fileTree'

const props = defineProps<{
  nodes: TreeNode[]
  selectedPaths: string[]
}>()

const emit = defineEmits<{
  'update:selectedPaths': [paths: string[]]
}>()

const allLeafPaths = computed(() => collectLeafPaths(props.nodes))

function togglePath(path: string): void {
  const next = props.selectedPaths.includes(path)
    ? props.selectedPaths.filter((item) => item !== path)
    : [...props.selectedPaths, path]
  emit('update:selectedPaths', next)
}

function selectAll(): void {
  emit('update:selectedPaths', allLeafPaths.value)
}

function clearAll(): void {
  emit('update:selectedPaths', [])
}
</script>

<template>
  <section class="page-card tree-panel">
    <div class="tree-header app-panel-title">
      <div>
        <h3 class="section-title">资源管理器</h3>
        <p class="muted">选择分析范围</p>
      </div>
      <span class="badge">{{ selectedPaths.length }}</span>
    </div>

    <div class="inline-actions tree-actions">
      <button class="btn-secondary" @click="selectAll">全选</button>
      <button class="btn-secondary" @click="clearAll">清空</button>
    </div>

    <ul class="tree-list">
      <FileTreeNode v-for="node in nodes" :key="node.id" :node="node" :selected-paths="selectedPaths" @toggle="togglePath" />
    </ul>
  </section>
</template>

<style scoped>
.tree-panel {
  height: 100%;
  padding: 6px;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 4px;
  background: var(--bg-sidebar);
}

.tree-header p {
  margin: 1px 0 0;
  font-size: 10px;
}

.tree-actions {
  padding-bottom: 1px;
}

.tree-list {
  margin: 0;
  padding: 0;
  overflow: auto;
}
</style>
