<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { ensureMermaid } from '@/utils/mermaid'

const props = defineProps<{
  code: string
  loading: boolean
}>()

const emit = defineEmits<{
  nodeClick: [label: string]
  error: [message: string]
}>()

const canvasRef = ref<HTMLElement | null>(null)
const canvasWrapRef = ref<HTMLElement | null>(null)
const scale = ref(1)
const translateX = ref(0)
const translateY = ref(0)
const isDragging = ref(false)
const dragStartX = ref(0)
const dragStartY = ref(0)
const dragStartTranslateX = ref(0)
const dragStartTranslateY = ref(0)
const renderError = ref('')

async function renderDiagram(): Promise<void> {
  if (!canvasRef.value || !props.code.trim()) return
  try {
    renderError.value = ''
    const mermaid = ensureMermaid()
    const renderId = `mermaid-${Date.now()}`
    const { svg } = await mermaid.render(renderId, props.code)
    canvasRef.value.innerHTML = svg

const clickableSelectors = [
  '.node',
  '.classGroup',
  '.actor',
  '.participant',
  'g[id*="flowchart"]',
  'g[id*="classid"]',
  'g[id*="actor"]',
]

const normalizeNodeText = (text: string): string => {
  return text
    .replace(/\s+/g, ' ')
    .replace(/^\+/, '')
    .replace(/\(\)$/, '')
    .trim()
}

const pickNodeKey = (element: Element): string => {
  const rawId = (element as HTMLElement).id || ''
  const rawText = element.textContent?.trim() || ''
  const text = normalizeNodeText(rawText)

  // flowchart: mermaid-xxx-flowchart-S2_1-8 -> S2_1
  const flowchartMatch = rawId.match(/flowchart-([A-Za-z0-9_]+)-\d+$/)
  if (flowchartMatch?.[1]) {
    return flowchartMatch[1]
  }

  // classDiagram: classid-User-xxx 或 classid-Module_main-xxx -> User / Module_main
  const classMatch = rawId.match(/classid-([A-Za-z0-9_]+)(?:-\d+)?/)
  if (classMatch?.[1]) {
    return classMatch[1]
  }

  // sequenceDiagram participant: actor-F1-xxx -> F1
  const actorMatch = rawId.match(/actor-([A-Za-z0-9_]+)(?:-\d+)?/)
  if (actorMatch?.[1]) {
    return actorMatch[1]
  }

  // 类图文本经常是：
  // User
  // +__init__()
  // 这里只取第一行作为类名
  const firstLine = rawText
    .split('\n')
    .map((line) => normalizeNodeText(line))
    .find(Boolean)

  return firstLine || text
}

const bindNodeClickEvents = () => {
  if (!canvasRef.value) return

  canvasRef.value.querySelectorAll(clickableSelectors.join(',')).forEach((element) => {
    element.addEventListener('click', () => {
      const nodeKey = pickNodeKey(element)

      console.log('clicked node:', {
        rawId: (element as HTMLElement).id || '',
        text: element.textContent?.trim() || '',
        nodeKey,
      })

      if (nodeKey) emit('nodeClick', nodeKey)
    })
  })
}

bindNodeClickEvents()

    await nextTick()
    translateX.value = 0
    translateY.value = 0
    autoFit()
  } catch (error) {
    renderError.value = error instanceof Error ? error.message : 'Mermaid 渲染失败'
    emit('error', renderError.value)
  }
}

function autoFit(): void {
  if (!canvasWrapRef.value || !canvasRef.value) return

  const svg = canvasRef.value.querySelector('svg')
  if (!svg) return

  const bbox = svg.getBBox()
  const svgWidth = bbox.width || svg.clientWidth || 100
  const svgHeight = bbox.height || svg.clientHeight || 100

  const containerWidth = canvasWrapRef.value.clientWidth - 12
  const containerHeight = canvasWrapRef.value.clientHeight - 12

  const scaleX = containerWidth / svgWidth
  const scaleY = containerHeight / svgHeight

  const newScale = Math.min(scaleX, scaleY) * 0.95

  scale.value = Math.min(4, Math.max(0.4, newScale))
}

function zoom(step: number): void {
  scale.value = Math.min(4, Math.max(0.4, scale.value + step))
}

function resetZoom(): void {
  scale.value = 1
  translateX.value = 0
  translateY.value = 0
}

const MAX_OFFSET = 2000

function onMouseDown(e: MouseEvent): void {
  isDragging.value = true
  dragStartX.value = e.clientX
  dragStartY.value = e.clientY
  dragStartTranslateX.value = translateX.value
  dragStartTranslateY.value = translateY.value
  document.addEventListener('mousemove', onMouseMove)
  document.addEventListener('mouseup', onMouseUp)
}

function onMouseMove(e: MouseEvent): void {
  if (!isDragging.value) return
  const dx = e.clientX - dragStartX.value
  const dy = e.clientY - dragStartY.value
  translateX.value = Math.max(-MAX_OFFSET, Math.min(MAX_OFFSET, dragStartTranslateX.value + dx))
  translateY.value = Math.max(-MAX_OFFSET, Math.min(MAX_OFFSET, dragStartTranslateY.value + dy))
}

function onMouseUp(): void {
  isDragging.value = false
  document.removeEventListener('mousemove', onMouseMove)
  document.removeEventListener('mouseup', onMouseUp)
}

function onWheel(e: WheelEvent): void {
  e.preventDefault()
  if (!canvasWrapRef.value || !canvasRef.value) return

  const rect = canvasWrapRef.value.getBoundingClientRect()
  const mouseX = e.clientX - rect.left
  const mouseY = e.clientY - rect.top

  const oldScale = scale.value
  const delta = e.deltaY > 0 ? -0.1 : 0.1
  const newScale = Math.min(4, Math.max(0.4, oldScale + delta))

  if (newScale !== oldScale) {
    const scaleRatio = newScale / oldScale
    translateX.value = mouseX - (mouseX - translateX.value) * scaleRatio
    translateY.value = mouseY - (mouseY - translateY.value) * scaleRatio
    scale.value = newScale
  }
}

defineExpose({
  getSvgElement: () => canvasRef.value?.querySelector('svg') as SVGElement | null,
  rerender: renderDiagram,
})

watch(
  () => props.code,
  async () => {
    await nextTick()
    await renderDiagram()
  },
  { immediate: true },
)
</script>

<template>
  <section class="page-card canvas-panel">
    <div class="canvas-toolbar app-panel-title">
      <div>
        <h3 class="section-title">编辑器</h3>
        <p class="muted">Mermaid 预览画布</p>
      </div>
      <div class="inline-actions">
        <button class="btn-secondary" @click="zoom(0.1)">+</button>
        <button class="btn-secondary" @click="zoom(-0.1)">-</button>
        <button class="btn-secondary" @click="resetZoom">1:1</button>
        <button class="btn-primary" @click="renderDiagram">重绘</button>
      </div>
    </div>

    <div ref="canvasWrapRef" class="canvas-wrap" :class="{ dragging: isDragging }" @mousedown="onMouseDown" @wheel.prevent="onWheel">
      <div v-if="loading" class="placeholder">图表处理中，请稍候...</div>
      <div v-else-if="renderError" class="placeholder error">{{ renderError }}</div>
      <div ref="canvasRef" class="mermaid-host" :style="{ transform: `translate(${translateX}px, ${translateY}px) scale(${scale})` }" />
    </div>
  </section>
</template>

<style scoped>
.canvas-panel {
  padding: 6px;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 4px;
  min-height: 0;
  background: var(--bg-sidebar);
  flex: 1;
}

.canvas-toolbar p {
  margin: 1px 0 0;
  font-size: 10px;
}

.canvas-wrap {
  position: relative;
  overflow: hidden;
  min-height: 0;
  border-radius: var(--radius-sm);
  background: var(--bg-elevated);
  border: 1px solid rgba(255, 255, 255, 0.04);
  padding: 6px;
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: grab;
}

.canvas-wrap.dragging {
  cursor: grabbing;
}

.mermaid-host {
  transform-origin: center center;
  width: auto;
  height: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.placeholder {
  display: grid;
  place-items: center;
  min-height: 140px;
  color: var(--muted);
  font-size: 11px;
}

.error {
  color: #efb7b0;
}

@media (max-width: 960px) {
  .canvas-toolbar {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>