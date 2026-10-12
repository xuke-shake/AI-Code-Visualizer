<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ensureMermaid, sanitizeMermaidCode } from '@/utils/mermaid'
import type { MermaidRenderEvent } from '@/types'

const props = defineProps<{
  code: string
  loading: boolean
  renderRequestKey?: number
}>()

const emit = defineEmits<{
  nodeClick: [label: string]
  error: [message: string]
  rendered: [event: MermaidRenderEvent]
  pending: [event: MermaidRenderEvent]
  renderError: [event: MermaidRenderEvent]
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
let renderSequence = 0
let successfulRenderSequence = 0
let successfulRenderCode = ''
let disposed = false
let fitTimer: ReturnType<typeof setTimeout> | undefined
let detachNodeClick: (() => void) | null = null

function nodeText(node: Element): string {
  return (node.querySelector('text')?.textContent || node.textContent || '').replace(/\s+/g, ' ').trim()
}

function attachNodeClickHandler(): void {
  if (!canvasRef.value) return
  detachNodeClick?.()
  const onClick = (event: Event) => {
    const target = event.target instanceof Element ? event.target : null
    const node = target?.closest('g.node, g.actor, g[class*="node"]')
    if (!node) return
    const label = nodeText(node)
    const nodeId = node.getAttribute('id') || ''
    emit('nodeClick', label || nodeId)
  }
  canvasRef.value.addEventListener('click', onClick)
  detachNodeClick = () => canvasRef.value?.removeEventListener('click', onClick)
}

async function renderDiagram(): Promise<void> {
  if (disposed || !canvasRef.value) return
  const sequence = ++renderSequence
  const sourceCode = props.code
  const requestKey = props.renderRequestKey ?? 0
  successfulRenderSequence = 0
  successfulRenderCode = ''
  emit('pending', { requestKey, code: sourceCode, sequence, status: 'pending' })
  canvasRef.value.innerHTML = ''
  detachNodeClick?.()
  detachNodeClick = null
  
  // 当 code 为空时，清空画布
  if (!sourceCode.trim()) {
    canvasRef.value.innerHTML = ''
    renderError.value = ''
    scale.value = 1
    translateX.value = 0
    translateY.value = 0
    return
  }

  try {
    renderError.value = ''
    const mermaid = ensureMermaid()
    const safeCode = sanitizeMermaidCode(sourceCode)
    const renderId = `mermaid-${Date.now()}-${sequence}`
    const { svg } = await mermaid.render(renderId, safeCode)
    if (sequence !== renderSequence || !canvasRef.value || props.code !== sourceCode) return
    canvasRef.value.innerHTML = svg

    // 等待 SVG 完全渲染到 DOM
    await nextTick()
    if (sequence !== renderSequence || !canvasRef.value || props.code !== sourceCode) return
    
    // 使用 viewBox 的原始尺寸，避免固定尺寸破坏宽图适配
    const svgElement = canvasRef.value.querySelector('svg')
    if (!svgElement || /Maximum text size/i.test(svgElement.textContent || '')) {
      throw new Error('Mermaid 未生成有效图表，请缩小源码或文件选择范围')
    }
    if (svgElement) {
      const viewBox = svgElement.getAttribute('viewBox')?.trim().split(/\s+/).map(Number)
      if (viewBox && viewBox.length === 4 && viewBox[2] > 0 && viewBox[3] > 0) {
        svgElement.setAttribute('width', String(viewBox[2]))
        svgElement.setAttribute('height', String(viewBox[3]))
        svgElement.style.width = `${viewBox[2]}px`
        svgElement.style.height = `${viewBox[3]}px`
      }
      svgElement.style.maxWidth = 'none'
    }

    // 再等待一小段时间确保 SVG 布局完成
    await new Promise(resolve => setTimeout(resolve, 30))
    if (disposed || sequence !== renderSequence || !canvasRef.value || props.code !== sourceCode) return
    autoFit()
    attachNodeClickHandler()
    successfulRenderSequence = sequence
    successfulRenderCode = sourceCode
    emit('rendered', { requestKey, code: sourceCode, sequence, status: 'success' })
  } catch (error) {
    if (sequence !== renderSequence || !canvasRef.value || props.code !== sourceCode) return
    canvasRef.value.innerHTML = ''
    renderError.value = error instanceof Error ? error.message : 'Mermaid 渲染失败'
    const event: MermaidRenderEvent = { requestKey, code: sourceCode, sequence, status: 'error', message: renderError.value }
    emit('renderError', event)
    emit('error', renderError.value)
  }
}

// ==============================================
// 获取 SVG 尺寸（公共函数）
// ==============================================
function getSvgSize(svg: SVGElement): { width: number; height: number } {
  const viewBox = svg.getAttribute('viewBox')?.trim().split(/\s+/).map(Number)
  let width = viewBox && viewBox.length === 4 ? viewBox[2] : 0
  let height = viewBox && viewBox.length === 4 ? viewBox[3] : 0
  if (!(width > 0 && height > 0)) {
    width = Number(svg.getAttribute('width')) || svg.clientWidth || 400
    height = Number(svg.getAttribute('height')) || svg.clientHeight || 300
  }

  return { width, height }
}

// ==============================================
// 自动适应画布
// ==============================================
function autoFit(): void {
  if (disposed || !canvasWrapRef.value || !canvasRef.value) return

  const svg = canvasRef.value.querySelector('svg')
  if (!svg) return

  // 获取容器尺寸
  const containerWidth = canvasWrapRef.value.clientWidth
  const containerHeight = canvasWrapRef.value.clientHeight
  
  // 如果容器尺寸为 0，可能还没布局完成，稍后重试
  if (containerWidth === 0 || containerHeight === 0) {
    clearTimeout(fitTimer)
    fitTimer = setTimeout(autoFit, 100)
    return
  }

  // 获取 SVG 尺寸（使用公共函数）
  const { width: svgWidth, height: svgHeight } = getSvgSize(svg)

  // 计算缩放比例
  const scaleX = containerWidth / svgWidth
  const scaleY = containerHeight / svgHeight

  // 使用较大的缩放比例，确保图表填满画布
  const newScale = Math.min(scaleX, scaleY) * 0.9

  // 限制缩放范围
  scale.value = Math.min(4, newScale)
  
  // 计算居中偏移
  const scaledWidth = svgWidth * scale.value
  const scaledHeight = svgHeight * scale.value
  const centerX = (containerWidth - scaledWidth) / 2
  const centerY = (containerHeight - scaledHeight) / 2
  
  translateX.value = centerX
  translateY.value = centerY
}

function zoom(step: number): void {
  scale.value = Math.min(4, Math.max(0.001, scale.value + step))
}

function resetZoom(): void {
  // 重置为 1:1 并居中
  scale.value = 1
  
  if (!canvasWrapRef.value || !canvasRef.value) {
    translateX.value = 0
    translateY.value = 0
    return
  }
  
  const svg = canvasRef.value.querySelector('svg')
  if (!svg) {
    translateX.value = 0
    translateY.value = 0
    return
  }
  
  const containerWidth = canvasWrapRef.value.clientWidth
  const containerHeight = canvasWrapRef.value.clientHeight
  
  // 获取 SVG 尺寸（使用公共函数）
  const { width: svgWidth, height: svgHeight } = getSvgSize(svg)
  
  // 计算居中偏移
  const centerX = (containerWidth - svgWidth) / 2
  const centerY = (containerHeight - svgHeight) / 2
  
  translateX.value = centerX
  translateY.value = centerY
}

function translationBounds(): { minX: number; maxX: number; minY: number; maxY: number } {
  const wrap = canvasWrapRef.value
  const svg = canvasRef.value?.querySelector('svg')
  if (!wrap || !svg) return { minX: -Infinity, maxX: Infinity, minY: -Infinity, maxY: Infinity }
  const { width, height } = getSvgSize(svg)
  const scaledWidth = width * scale.value
  const scaledHeight = height * scale.value
  const viewportWidth = wrap.clientWidth
  const viewportHeight = wrap.clientHeight
  const overlapX = Math.min(48, scaledWidth / 2, viewportWidth / 2)
  const overlapY = Math.min(48, scaledHeight / 2, viewportHeight / 2)
  return {
    minX: overlapX - scaledWidth,
    maxX: viewportWidth - overlapX,
    minY: overlapY - scaledHeight,
    maxY: viewportHeight - overlapY,
  }
}

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
  const bounds = translationBounds()
  translateX.value = Math.max(bounds.minX, Math.min(bounds.maxX, dragStartTranslateX.value + dx))
  translateY.value = Math.max(bounds.minY, Math.min(bounds.maxY, dragStartTranslateY.value + dy))
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
  
  // 鼠标在容器中的位置（相对于容器左上角）
  const mouseX = e.clientX - rect.left
  const mouseY = e.clientY - rect.top

  const oldScale = scale.value
  const delta = e.deltaY > 0 ? -0.1 : 0.1
  const newScale = Math.min(4, Math.max(0.001, oldScale + delta))

  if (newScale !== oldScale) {
    // 计算鼠标在缩放后的画布上的位置（考虑当前的平移和缩放）
    const canvasMouseX = (mouseX - translateX.value) / oldScale
    const canvasMouseY = (mouseY - translateY.value) / oldScale
    
    // 新的平移应该保持鼠标指向的点不变
    translateX.value = mouseX - canvasMouseX * newScale
    translateY.value = mouseY - canvasMouseY * newScale
    scale.value = newScale
  }
}

defineExpose({
  getSvgElement: () => {
    if (disposed || props.loading || !canvasRef.value || successfulRenderSequence !== renderSequence || successfulRenderCode !== props.code || renderError.value) return null
    return canvasRef.value.querySelector('svg') as SVGElement | null
  },
  rerender: renderDiagram,
})

// 组件挂载后确保 autoFit 执行一次
onMounted(() => {
  fitTimer = setTimeout(() => {
    autoFit()
  }, 150)
})

onBeforeUnmount(() => {
  disposed = true
  clearTimeout(fitTimer)
  renderSequence += 1
  detachNodeClick?.()
  detachNodeClick = null
  document.removeEventListener('mousemove', onMouseMove)
  document.removeEventListener('mouseup', onMouseUp)
})

watch(
  () => [props.code, props.renderRequestKey],
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
  flex: 1;
  cursor: grab;
}

.canvas-wrap.dragging {
  cursor: grabbing;
}

.mermaid-host {
  transform-origin: 0 0;
  position: absolute;
  top: 0;
  left: 0;
}

.placeholder {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: center;
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
