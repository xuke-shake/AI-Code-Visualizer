<script setup lang="ts">
import { computed } from 'vue'
import type { FileTreeNode } from '@/types'

const props = defineProps<{
  node: FileTreeNode
  selectedPaths: string[]
}>()

const emit = defineEmits<{
  toggle: [path: string]
}>()

const checked = computed(() => props.selectedPaths.includes(props.node.path))
</script>

<template>
  <li class="tree-node">
    <div class="node-row">
      <template v-if="node.type === 'file'">
        <input type="checkbox" :checked="checked" @change="emit('toggle', node.path)" />
      </template>
      <span class="node-name">{{ node.name }}</span>
    </div>

    <ul v-if="node.children?.length" class="tree-children">
      <FileTreeNode
        v-for="child in node.children"
        :key="child.id"
        :node="child"
        :selected-paths="selectedPaths"
        @toggle="emit('toggle', $event)"
      />
    </ul>
  </li>
</template>

<style scoped>
.tree-node {
  list-style: none;
}

.node-row {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 0;
  min-height: 20px;
}

.node-row :deep(input[type='checkbox']) {
  width: 12px;
  min-height: 12px;
  height: 12px;
  padding: 0;
}

.node-name {
  color: var(--text-soft);
  font-size: 11px;
}

.tree-children {
  margin: 0;
  padding-left: 12px;
}
</style>
