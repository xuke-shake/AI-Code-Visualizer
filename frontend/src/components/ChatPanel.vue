<script setup lang="ts">
import { reactive, ref } from 'vue'
import type { DiagramType } from '@/types'

const props = defineProps<{
  pending: boolean
  selectedCount: number
}>()

const emit = defineEmits<{
  generate: [payload: { instruction: string; type: DiagramType }]
}>()

const form = reactive({
  instruction: '请根据已选源码中能够确认的结构或关系生成图表，不要补充源码无法证明的业务语义。',
  type: 'flowchart' as DiagramType,
})
const validationMessage = ref('')

function submit(): void {
  validationMessage.value = ''
  if (props.pending) return
  if (props.selectedCount === 0) {
    validationMessage.value = '请至少选择一个已解析文件。'
    return
  }
  const instruction = form.instruction.trim()
  if (!instruction) {
    validationMessage.value = '请输入生成指令。'
    return
  }
  if (instruction.length > 4000) {
    validationMessage.value = '生成指令不能超过 4000 个字符。'
    return
  }
  emit('generate', { ...form, instruction })
}
</script>

<template>
  <section class="page-card chat-card">
    <div class="chat-header app-panel-title">
      <div>
        <h3 class="section-title">AI 指令</h3>
        <p class="muted">已选 {{ selectedCount }} 个文件</p>
      </div>
      <span class="badge">Mermaid</span>
    </div>

    <textarea v-model="form.instruction" placeholder="请输入生成图表的中文指令" />
    <p v-if="validationMessage" class="validation-message">{{ validationMessage }}</p>

    <div class="chat-actions">
      <select v-model="form.type">
        <option value="flowchart">流程图</option>
        <option value="sequenceDiagram">时序图</option>
        <option value="stateDiagram">状态图</option>
        <option value="classDiagram">架构类图</option>
      </select>
      <button class="btn-primary" :disabled="pending || selectedCount === 0" @click="submit">
        {{ pending ? '生成中...' : selectedCount === 0 ? '请先选择文件' : '生成图表' }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.chat-card {
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  background: var(--bg-sidebar);
  height: 100%;
}

.chat-header p {
  margin: 1px 0 0;
  font-size: 10px;
}

.chat-actions {
  display: grid;
  grid-template-columns: 1fr 70px;
  gap: 4px;
}
/* 让下拉框和按钮变紧凑 */
.chat-actions select,
.chat-actions button {
  padding: 4px 8px;       /* 上下左右内边距缩小 */
  font-size: 12px;         /* 字体缩小 */
  height: 28px;            /* 整体高度缩小 */
  border-radius: 3px;     /* 圆角也缩小，更精致 */
}

/* 如果你想让按钮更窄一点，也可以单独设置 */
.chat-actions button {
  width: auto;             /* 让宽度随内容自适应 */
  min-width: 60px;         /* 给个最小宽度，防止太挤 */
}

textarea {
  flex: 1;
  min-height: 0;
  resize: none;
}
.validation-message {
  margin: 0;
  color: #efb7b0;
  font-size: 11px;
}
</style>
