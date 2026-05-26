<script setup lang="ts">
// ==============================================
// 1. 引入依赖：Vue核心功能、路由、组件、状态管理、工具函数
// ==============================================
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

// 引入页面里的子组件
import MermaidCanvas from '@/components/MermaidCanvas.vue'
import FileTree from '@/components/FileTree.vue'
import SourcePanel from '@/components/SourcePanel.vue'
import ChatPanel from '@/components/ChatPanel.vue'
import ProgressBar from '@/components/ProgressBar.vue'
import ExportDialog from '@/components/ExportDialog.vue'

// 引入Pinia状态管理（全局数据中心）
import { useDiagramStore } from '@/stores/diagramStore'
import { useProjectStore } from '@/stores/projectStore'
import { useTaskStore } from '@/stores/taskStore'
import { useUserStore } from '@/stores/userStore'

// 引入工具函数（通用功能）
import { collectLeafPaths } from '@/utils/fileTree'
import { downloadSvgAsPdf, downloadSvgAsPng, downloadText } from '@/utils/download'
import { formatDateTime, getProjectStatusLabel } from '@/utils/format'

// 引入TypeScript类型定义（规范变量格式）
import type { ExportType } from '@/types'

// ==============================================
// 2. 初始化路由 & 状态管理工具
// ==============================================
const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const projectStore = useProjectStore()
const diagramStore = useDiagramStore()
const taskStore = useTaskStore()

// ==============================================
// 3. 模板引用 & 页面状态变量
// ==============================================
const canvasRef = ref<InstanceType<typeof MermaidCanvas> | null>(null)
const exportVisible = ref(false)
const selectedPaths = ref<string[]>([])
const infoMessage = ref('')

// ==============================================
// 4. 面板尺寸变量（拖拽时动态修改）
// ==============================================
const leftPanelWidth = ref(250)
const bottomPanelHeight = ref(180)
const sourcePanelWidth = ref(200)
const aiPanelWidth = ref(200)
const chatPanelHeight = ref(350)      
const progressPanelHeight = ref(300 )  

// ==============================================                         
// 5. 面板显示/隐藏控制变量  
// ==============================================
const leftPanelVisible = ref(true)
const bottomPanelVisible = ref(true)
const sourcePanelVisible = ref(true)
const aiPanelVisible = ref(true)
const noticeVisible = ref(true)

// ==============================================
// 6. 拖拽状态变量
// ==============================================
const isDragging = ref(false)
const dragType = ref<'left' | 'bottom' | 'right' | 'source' | 'ai' | 'chat' | 'progress' |  null>(null)

// ==============================================
// 7. 计算属性：从路由自动获取项目ID
// ==============================================
const projectId = computed(() => String(route.params.projectId))
const currentProject = computed(() => projectStore.currentProject)

// ==============================================
// 8. 页面初始化函数
// ==============================================
async function bootstrap() {
  await projectStore.fetchProjects()
  await projectStore.selectProject(projectId.value)
  await diagramStore.fetchDiagram(projectId.value)
  selectedPaths.value = collectLeafPaths(projectStore.fileTree)
  taskStore.connect(projectId.value)
}

// ==============================================
// 9. 生成图表
// ==============================================
async function handleGenerate(payload: { instruction: string; type: 'flowchart' | 'sequenceDiagram' | 'stateDiagram' | 'classDiagram' }) {
  infoMessage.value = '已提交图表生成任务，请关注实时进度。'
  await diagramStore.generateDiagram(projectId.value, {
    ...payload,
    selectedPaths: selectedPaths.value,
  })
}

// ==============================================
// 10. 保存Mermaid源码到后端
// ==============================================
async function handleSave() {
  await diagramStore.saveDiagram(projectId.value)
  infoMessage.value = 'Mermaid 已保存并完成重绘。'
}

// ==============================================
// 11. 导出功能
// ==============================================
async function handleExport(type: ExportType) {
  await diagramStore.exportMermaid(projectId.value, type)
  const svg = canvasRef.value?.getSvgElement()

  if (type === 'markdown') {
    downloadText(`\`\`\`mermaid\n${diagramStore.editorContent}\n\`\`\``, `${diagramStore.currentDiagram?.title || 'diagram'}.md`, 'text/markdown')
    return
  }

  if (!svg) {
    infoMessage.value = '当前图表未渲染完成，暂无法导出。'
    return
  }

  if (type === 'svg') {
    downloadText(new XMLSerializer().serializeToString(svg), `${diagramStore.currentDiagram?.title || 'diagram'}.svg`, 'image/svg+xml')
    return
  }

  if (type === 'png') {
    await downloadSvgAsPng(svg, `${diagramStore.currentDiagram?.title || 'diagram'}.png`)
    return
  }

  await downloadSvgAsPdf(svg, `${diagramStore.currentDiagram?.title || 'diagram'}.pdf`)
}

// ==============================================
// 12. 分享项目
// ==============================================
async function handleShare() {
  const url = await diagramStore.share(projectId.value)
  if (url) {
    await navigator.clipboard.writeText(url)
    infoMessage.value = '分享链接已生成并复制到剪贴板。'
  }
}

// ==============================================
// 13. 同步代码
// ==============================================
async function handleSync() {
  await projectStore.syncCurrentProject()
  infoMessage.value = '已启动代码同步，图表完成后会标记为过期。'
}

// ==============================================
// 14. 退出登录
// ==============================================
function logout() {
  userStore.logout()
  router.push('/login')
}
                                                    
// ==============================================
// 15. 监听任务状态
// ==============================================
watch(
  () => taskStore.currentTask,
  async (task) => {
    if (task?.status === 'success') {
      await projectStore.fetchProjects()
      await projectStore.selectProject(projectId.value)
      await diagramStore.refreshDiagram(projectId.value)
    }
  },
)

// ==============================================
// 16. 拖拽逻辑
// ==============================================
let dragAnimationFrame: number | null = null

function startDrag(type: 'left' | 'bottom' | 'right' | 'source' | 'ai' , event: MouseEvent) {
  isDragging.value = true
  dragType.value = type
  event.preventDefault()
}

function handleDrag(event: MouseEvent) {
  if (!isDragging.value || !dragType.value) return
  if (dragAnimationFrame) cancelAnimationFrame(dragAnimationFrame)

  dragAnimationFrame = requestAnimationFrame(() => {
    if (!isDragging.value || !dragType.value) return

    switch (dragType.value) {
      case 'left':
        leftPanelWidth.value = Math.max(5, Math.min(400, event.clientX))
        break
      case 'bottom': {
        const rect = document.querySelector('.center-column')?.getBoundingClientRect()
        if (rect) bottomPanelHeight.value = Math.max(5, Math.min(400, rect.bottom - event.clientY))
        break
      }
      case 'source': {
        const rect = document.querySelector('.source-panel-wrapper')?.getBoundingClientRect()
        if (rect) {
          sourcePanelWidth.value = Math.max(3, Math.min(500, rect.right - event.clientX))
        }
        break
      }
      case 'ai': {
        const rect = document.querySelector('.ai-panel-wrapper')?.getBoundingClientRect()
        if (rect) {
          aiPanelWidth.value = Math.max(5, Math.min(500, rect.right - event.clientX))
        }
        break
      }
      case 'chat': {
        const rect = document.querySelector('.ai-panel-wrapper')?.getBoundingClientRect()
        if (rect) {
          const headerHeight = 28
          const newHeight = event.clientY - rect.top - headerHeight
          chatPanelHeight.value = Math.max(5, Math.min(300, newHeight))
        }
        break
      }
    }
  })
}

function stopDrag() {
  isDragging.value = false
  dragType.value = null
  if (dragAnimationFrame) {
    cancelAnimationFrame(dragAnimationFrame)
    dragAnimationFrame = null
  }
}


// ==============================================
// 18. 窗口菜单控制
// ==============================================
const showWindowMenu = ref(false)

function restorePanel(panel: 'left' | 'bottom' | 'source' | 'ai') {
  switch (panel) {
    case 'left':
      leftPanelVisible.value = true
      leftPanelWidth.value =250
      break
    case 'bottom':
      bottomPanelVisible.value = true
      bottomPanelHeight.value = 180
      break
    case 'source':
      sourcePanelVisible.value = true
      sourcePanelWidth.value = 200
      break
    case 'ai':
      aiPanelVisible.value = true
      aiPanelWidth.value = 200
      break
  }
  showWindowMenu.value = false
}

// ==============================================
// 19. 生命周期
// ==============================================
onMounted(() => {
  bootstrap()
  document.addEventListener('mousemove', handleDrag)
  document.addEventListener('mouseup', stopDrag)

  // 点击外部关闭窗口菜单
  const handleClickOutside = (e: MouseEvent) => {
    const menu = document.querySelector('.window-menu')
    const btn = document.querySelector('.window-btn')
    if (menu && btn && !menu.contains(e.target as Node) && !btn.contains(e.target as Node)) {
      showWindowMenu.value = false
    }
  }
  document.addEventListener('click', handleClickOutside)
  onBeforeUnmount(() => document.removeEventListener('click', handleClickOutside))
})

onBeforeUnmount(() => {
  taskStore.disconnect()
  document.removeEventListener('mousemove', handleDrag)
  document.removeEventListener('mouseup', stopDrag)
})
</script>

<template>
  <main class="page-shell workspace-page">
    <!-- 顶部标题栏 -->
    <header class="page-card workspace-header">
      <div class="header-left">
        <span class="badge">工作区</span>
        <div>
          <h1>{{ currentProject?.name || '正在加载项目...' }}</h1>
          <p class="muted">
            状态：{{ currentProject ? getProjectStatusLabel(currentProject.status) : '--' }}
            · 最近更新：{{ currentProject ? formatDateTime(currentProject.updatedAt) : '--' }}
          </p>
        </div>
      </div>
      <div class="toolbar header-actions">
        <div class="window-dropdown">
          <button class="btn-secondary window-btn"  @click.stop="showWindowMenu = !showWindowMenu">
            窗口
          </button>
          <div v-if="showWindowMenu" class="window-menu">
            <div class="menu-item" @click="restorePanel('left')">文件树</div>
            <div class="menu-item" @click="restorePanel('bottom')">Mermaid 源码</div>
            <div class="menu-item" @click="restorePanel('source')">源码面板</div>
            <div class="menu-item" @click="restorePanel('ai')">AI指令/任务进度</div>
          </div>
        </div>

        <button class="btn-secondary" @click="router.push('/projects')">项目列表</button>
        <button v-if="userStore.isAdmin" class="btn-secondary" @click="router.push('/admin')">管理员后台</button>
        <button class="btn-secondary" @click="handleSync">同步代码</button>
        <button class="btn-primary" @click="exportVisible = true">导出</button>
        <button class="btn-secondary" @click="logout">退出</button>
      </div>
    </header>

    <div class="workspace-notices">
      <div v-if="noticeVisible && (currentProject?.status === 'outdated' || diagramStore.currentDiagram?.outdated)" class="page-card notice warning">
        <button class="workspace-notices-btn" @click="noticeVisible = false">×</button>
        当前图表已过期，建议重新生成 Mermaid 结果。
      </div>
      <div v-if="infoMessage" class="page-card notice info">
        <button class ="workspace-notices-btn" @click="infoMessage = ''">×</button>
        {{ infoMessage }}
      </div>
    </div>

    <!-- 主工作区 -->
    <section class="workspace-grid" :class="{ dragging: isDragging }">
      <!-- 左侧文件树 -->
      <div  v-if="leftPanelVisible" class="left-column" :style="{ width: leftPanelWidth + 'px' }" >
        <div class="panel-header">
          <span class="panel-title">文件树</span>
          <button class="panel-toggle" @click="leftPanelVisible = false">×</button>
        </div>
        <FileTree :nodes="projectStore.fileTree" :selected-paths="selectedPaths" @update:selected-paths="selectedPaths = $event" />
        <div class="resizer resizer-right" :class="{ active: dragType === 'left' }" @mousedown="startDrag('left', $event)"></div>
      </div>

      <!-- 中间画布 + 底部编辑器 -->
      <div class="center-column">
        <div class="canvas-area">
          <MermaidCanvas
            ref="canvasRef"
            :code="diagramStore.editorContent"
            :loading="diagramStore.loading"
            @node-click="diagramStore.selectNode"
            @error="infoMessage = $event"
          />
        </div>

        <div v-if="bottomPanelVisible"  class="workspace-bottom" :style="{ height: bottomPanelHeight + 'px' }">
          <div v-if="bottomPanelVisible" class="resizer resizer-bottom" :class="{ active: dragType === 'bottom' }" @mousedown="startDrag('bottom', $event)" ></div>
          <section class="page-card editor-card">
            <div class="editor-header app-panel-title">
              <div>
                <h3 class="section-title">Mermaid 源码</h3>
                <p class="muted">手动修改后实时重绘</p>
              </div>
              <div class="toolbar">
                <button class="panel-toggle" @click="bottomPanelVisible = false">×</button>
                <button class="btn-secondary" @click="canvasRef?.rerender()">重绘</button>
                <button class="btn-primary" @click="handleSave">保存</button>
              </div>
            </div>
            <textarea :value="diagramStore.editorContent" @input="diagramStore.setEditorContent(($event.target as HTMLTextAreaElement).value)" />
          </section>
        </div>
      </div>

      <!-- 右侧面板 -->
      <div v-if="sourcePanelVisible || aiPanelVisible" class="right-column" >
        <div class="right-panel-container">
          <div v-if="sourcePanelVisible" class="source-panel-wrapper" :style="{ width: sourcePanelWidth + 'px' }">
            <div class="panel-header">
              <span class="panel-title">源码</span>
              <button class="panel-toggle" @click="sourcePanelVisible = false">×</button>
            </div>
            <SourcePanel :selected-label="diagramStore.selectedNode" :source="diagramStore.selectedSource" />
            <div v-if="aiPanelVisible" class="resizer resizer-left" :class="{ active: dragType === 'source' }" @mousedown="startDrag('source', $event)" ></div>
          </div>

          <div v-if="aiPanelVisible" class="ai-panel-wrapper" :style="{ width: aiPanelWidth + 'px' }" >
            <div class="panel-header">
              <span class="panel-title">AI指令</span>
              <button class="panel-toggle" @click="aiPanelVisible = false">×</button>
            </div>
            <!-- ChatPanel 区域 -->
            <div class="chat-panel-wrapper" :style="{ height: `${chatPanelHeight}px` }">
              <ChatPanel :pending="diagramStore.loading" :selected-count="selectedPaths.length" @generate="handleGenerate" />
            </div>
            <!-- ProgressBar 区域 -->
            <div class="progress-panel-wrapper" :style="{ height: `${progressPanelHeight}px` }">
              <ProgressBar :task="taskStore.currentTask" :history="taskStore.taskHistory" :socket-status="taskStore.socketStatus" />
            </div>
            <div class="resizer resizer-left"  :class="{ active: dragType === 'ai' }" @mousedown="startDrag('ai', $event)"></div>
          </div>
        </div>
      </div>
    </section>

    <!-- 导出弹窗 -->
    <ExportDialog :visible="exportVisible" :share-url="diagramStore.shareUrl" @close="exportVisible = false" @share="handleShare" @export="handleExport" />
  </main>
</template>
<style scoped>
/* 整个工作区最外层页面容器
 * Grid 布局：垂直方向分为三行
 */
.workspace-page {
  display: grid; 
  grid-template-rows: auto auto minmax(0, 1fr); /* 三行：头部自动、通知自动、内容区占满剩余空间 */
  gap: 4px; /* 子元素之间的间距 */
  height: 100%; 
}

/* 工作区顶部标题栏容器 */
.workspace-header {
  padding: 6px 8px; /* 内边距 */
  min-height: var(--titlebar-height); /* 最小高度，使用全局CSS变量 */
  display: flex; /* 弹性布局 */
  justify-content: space-between; /* 左右两端对齐 */
  align-items: center; /* 垂直方向居中 */
  gap: 6px; /* 子元素间距 */
  background: var(--bg-elevated); /* 背景色，使用全局变量 */
}

/* 标题栏左侧内容容器 */
.header-left {
  display: flex; /* 弹性布局 */
  align-items: center; /* 垂直居中 */
  gap: 6px; /* 子元素间距 */
}

/* 页面主标题样式 */
.workspace-header h1 {
  margin: 0; /* 清除默认外边距 */
  font-size: 13px; /* 字体大小 */
  font-weight: 600; /* 字体粗细 */
}

/* 标题栏描述文本样式 */
.workspace-header p {
  margin: 1px 0 0; /* 上边距1px，其余为0 */
  font-size: 10px; /* 字体大小 */
}

/* 通知消息整体容器 */
.workspace-notices {
  display: grid; /* 网格布局 */
  gap: 4px; /* 通知之间的间距 */
}

/* 单条通知公共样式 */
.notice {
  min-height: 22px; /* 最小高度 */
  padding: 4px 6px; /* 内边距 */
  display: flex; /* 弹性布局 */
  align-items: center; /* 垂直居中 */
  font-size: 11px; /* 字体大小 */
}

/* 警告类型通知样式 */
.notice.warning {
  color: var(--notice-info-text); /* 文字颜色 */
  border-color: var(--notice-warning-border); /* 边框颜色 */
}

/* 信息类型通知样式 */
.notice.info {
  color: var(--notice-info-text); /* 文字颜色 */
}

/* 中间工作区布局容器（左+中+右面板） */
.workspace-grid {
  height: 100%; /* 占满父容器高度 */
  min-height: 0; /* 解决flex布局子元素溢出问题 */
  display: flex; /* 弹性布局 */
  gap: 4px; /* 子元素间距 */
  align-items: stretch; /* 子元素高度自动拉伸填充 */
}

/* 拖拽调整大小时的状态样式 */
.workspace-grid.dragging {
  user-select: none; /* 禁止选中页面文字 */
}

/* 拖拽状态下所有元素的鼠标样式 */
.workspace-grid.dragging * {
  cursor: ew-resize !important; /* 强制显示横向拖拽鼠标 */
}

/* 底部拖拽时的鼠标样式 */
.workspace-grid.dragging .resizer-bottom,
.workspace-grid.dragging .resizer-bottom * {
  cursor: ns-resize !important; /* 强制显示纵向拖拽鼠标 */
}

/* 左侧面板 + 右侧面板公共样式 */
.left-column,
.right-column {
  display: flex; /* 弹性布局 */
  flex-direction: column; /* 垂直方向排列 */
  position: relative; /* 相对定位，用于内部绝对定位元素 */
  flex-shrink: 0; /* 不允许宽度被压缩 */
  background: var(--bg-elevated); /* 背景色 */
  border: 1px solid var(--border-color); /* 边框样式 */
  border-radius: 4px; /* 圆角 */
  overflow: hidden; /* 隐藏超出容器的内容 */
  min-height: 0; /* 解决flex溢出问题 */
}

/* 中间画布区域容器 */
.center-column {
  flex: 1; /* 占满剩余宽度 */
  display: flex; /* 弹性布局 */
  flex-direction: column; /* 垂直排列 */
  position: relative; /* 相对定位 */
  overflow: hidden; /* 隐藏溢出内容 */
  min-height: 0; /* 解决flex溢出 */
  /* 动态内边距：底部面板展开时留出空间 */
  padding-bottom: v-bind('bottomPanelVisible ? `${bottomPanelHeight}px` : "0px"');
}

/* 画布展示区域（核心编辑区） */
.canvas-area {
  flex: 1 1 0; /* 可伸缩，占满剩余空间 */
  position: relative; /* 相对定位 */
  background: var(--bg-elevated); /* 背景色 */
  border: 1px solid var(--border-color); /* 边框 */
  border-radius: 4px; /* 圆角 */
  overflow: hidden; /* 隐藏溢出 */
  min-height: 0; /* 解决flex溢出 */
  display: flex; /* 弹性布局 */
  align-items: stretch; /* 高度拉伸 */
  justify-content: stretch; /* 宽度拉伸 */
}

/* 底部面板（日志/输出栏） */
.workspace-bottom {
  position: absolute; /* 绝对定位 */
  bottom: 0; /* 贴紧底部 */
  left: 0; /* 贴紧左侧 */
  right: 0; /* 贴紧右侧 */
  height: v-bind('`${bottomPanelHeight}px`'); /* 动态绑定高度 */
  transition: height 0.2s ease; /* 高度变化平滑过渡 */
  overflow: hidden; /* 隐藏溢出内容 */
  z-index: 5; /* 层级 */
  display: flex; /* 弹性布局 */
  flex-direction: column; /* 垂直排列 */
}

/* 右侧面板内部容器 */
.right-panel-container {
  display: flex; /* 弹性布局 */
  flex-direction: row; /* 水平排列 */
  gap: 4px; /* 子元素间距 */
  height: 100%; /* 占满父容器高度 */
  min-height: 0; /* 解决flex溢出 */
  flex: 1; /* 占满剩余空间 */
}

/* 资源面板 + AI面板外层公共容器 */
.source-panel-wrapper,
.ai-panel-wrapper {
  position: relative; /* 相对定位 */
  flex: none; /* 固定尺寸，不自动伸缩 */
  height: 100%; /* 占满父容器高度 */
}

/* 资源面板内部布局 */
.source-panel-wrapper {
  display: grid; /* 网格布局 */
  grid-template-rows: auto minmax(0, 1fr); /* 两行：头部自动高度，内容区占满剩余 */
  gap: 0; /* 间距为0 */
  min-height: 0; /* 解决flex溢出 */
}

/* AI面板改为 flex column 布局 */
.ai-panel-wrapper {
  display: flex;
  flex-direction: column;
}

/* AI面板头部样式 */
.ai-panel-wrapper .panel-header {
  flex-shrink: 0; /* 不允许压缩高度 */
}

/* ChatPanel 和 ProgressBar 包装器 */
.chat-panel-wrapper,
.progress-panel-wrapper {
  overflow: hidden;
  min-height: 0;
}

/* 水平拖拽条 */
.resizer-horizontal {
  height: 4px;
  width: 100%;
  cursor: ns-resize;
  background: transparent;
  transition: background-color 0.15s ease;
  flex-shrink: 0;
}

.resizer-horizontal:hover,
.resizer-horizontal.active {
  background-color: var(--accent-color);
}

/* 拖拽时水平拖拽条的鼠标样式 */
.workspace-grid.dragging .resizer-horizontal {
  cursor: ns-resize !important;
}

/* 编辑器卡片容器 */
.editor-card {
  padding: 6px; /* 内边距 */
  display: flex; /* 弹性布局 */
  flex-direction: column; /* 垂直排列 */
  gap: 4px; /* 子元素间距 */
  background: var(--bg-elevated); /* 背景色 */
  height: 100%; /* 占满父容器高度 */
  min-height: 0; /* 解决flex溢出 */
}

/* 编辑器头部 */
.editor-header {
  display: flex; /* 弹性布局 */
  justify-content: space-between; /* 左右两端对齐 */
  align-items: center; /* 垂直居中 */
}

/* 编辑器头部描述文本 */
.editor-header p {
  margin: 1px 0 0; /* 上边距 */
  font-size: 10px; /* 字体大小 */
}

/* 编辑器输入框 */
.editor-card textarea {
  flex: 1 1 0; /* 可伸缩 */
  min-height: 0; /* 解决flex溢出 */
  font-family: Consolas, 'Courier New', monospace; /* 等宽编程字体 */
  resize: none; /* 禁止手动拖拽缩放 */
}

/* 所有面板公共头部样式 */
.panel-header {
  display: flex; /* 弹性布局 */
  align-items: center; /* 垂直居中 */
  justify-content: space-between; /* 左右两端对齐 */
  padding: 4px 6px; /* 内边距 */
  background: var(--bg-elevated); /* 背景色 */
  border-bottom: 1px solid var(--border-color); /* 底部边框 */
  min-height: 24px; /* 最小高度 */
}

/* 面板标题文本 */
.panel-title {
  font-size: 11px; /* 字体大小 */
  font-weight: 500; /* 字体粗细 */
  color: var(--text-muted); /* 文字颜色 */
}

/* 面板折叠/展开按钮 */
.panel-toggle {
  width: 20px; /* 宽度 */
  height: 20px; /* 高度 */
  min-height: 20px; /* 最小高度 */
  padding: 0; /* 无内边距 */
  display: flex; /* 弹性布局 */
  align-items: center; /* 垂直居中 */
  justify-content: center; /* 水平居中 */
  background: transparent; /* 透明背景 */
  border: none; /* 无边框 */
  color: var(--text-muted); /* 图标颜色 */
  cursor: pointer; /* 鼠标手势 */
  font-size: 14px; /* 字体/图标大小 */
  line-height: 1; /* 行高 */
  border-radius: 2px; /* 圆角 */
}

/* 面板按钮悬浮效果 */
.panel-toggle:hover {
  background: var(--bg-hover); /* 悬浮背景色 */
  color: var(--text-primary); /* 悬浮文字颜色 */
}
.workspace-notices-btn {
  background: transparent; /* 透明背景 */
  border: none; /* 无边框 */
  color: var(--text-muted); /* 图标颜色 */
  cursor: pointer; /* 鼠标手势 */
  font-size: 14px; /* 字体/图标大小 */
  line-height: 1; /* 行高 */
  padding: 0; /* 无内边距 */
}




/* 拖拽调整大小手柄（通用） */
.resizer {
  position: absolute; /* 绝对定位 */
  z-index: 10; /* 层级最高 */
  top: 0; /* 贴紧顶部 */
  bottom: 0; /* 贴紧底部 */
  width: 4px; /* 宽度 */
  cursor: col-resize; /* 鼠标手势 */
  transition: background-color 0.15s ease; /* 背景色过渡动画 */
  background: transparent; /* 默认透明 */
}

/* 拖拽手柄悬浮/激活状态 */
.resizer:hover,
.resizer.active {
  background-color: var(--accent-color); /* 高亮背景色 */
}

/* 右侧拖拽手柄 */
.resizer-right {
  width: 4px; /* 宽度 */
  height: 100%; /* 高度铺满 */
  right: 0; /* 贴紧右侧 */
  top: 0; /* 贴紧顶部 */
  cursor: ew-resize; /* 横向拖拽鼠标 */
}

/* 左侧拖拽手柄 */
.resizer-left {
  width: 4px; /* 宽度 */
  height: 100%; /* 高度铺满 */
  left: 0; /* 贴紧左侧 */
  top: 0; /* 贴紧顶部 */
  cursor: ew-resize; /* 横向拖拽鼠标 */
}

/* 底部拖拽手柄 */
.resizer-bottom {
  height: 4px; /* 高度 */
  width: 100%; /* 宽度铺满 */
  bottom: 0; /* 贴紧底部 */
  left: 0; /* 贴紧左侧 */
  cursor: ns-resize; /* 纵向拖拽鼠标 */
  z-index: 9999; /* 确保在所有元素之上 */
}

/* 窗口下拉菜单容器 */
.window-dropdown {
  position: relative; /* 相对定位 */
  display: inline-block; /* 行内块元素 */
}

/* 窗口菜单按钮 */
.window-btn {
  padding: 4px 10px; /* 内边距 */
  display: flex; /* 弹性布局 */
  align-items: center; /* 垂直居中 */
  gap: 4px; /* 子元素间距 */
}

/* 下拉菜单面板 */
.window-menu {
  position: absolute; /* 绝对定位 */
  top: 100%; /* 显示在按钮下方 */
  left: 0; /* 贴紧左侧 */
  margin-top: 2px; /* 上边距 */
  background: var(--bg-elevated); /* 背景色 */
  border: 1px solid var(--border-color); /* 边框 */
  border-radius: 4px; /* 圆角 */
  box-shadow: var(--shadow-dropdown); /* 阴影 */
  z-index: 100; /* 最高层级 */
  min-width: 160px; /* 最小宽度 */
  padding: 4px 0; /* 上下内边距 */
}

/* 下拉菜单项 */
.menu-item {
  padding: 6px 16px; /* 内边距 */
  cursor: pointer; /* 鼠标手势 */
  font-size: 13px; /* 字体大小 */
  color: var(--text-primary); /* 文字颜色 */
}

/* 菜单项悬浮效果 */
.menu-item:hover {
  background: var(--bg-hover); /* 悬浮背景色 */
}

/* ==================== 响应式适配 ==================== */
/* 屏幕宽度 ≤1440px 时 */
@media (max-width: 1440px) {
  .workspace-bottom {
    grid-template-columns: minmax(0, 1fr) 240px; /* 底部面板布局调整 */
  }
}

/* 屏幕宽度 ≤1280px 时（平板/小屏电脑） */
@media (max-width: 1280px) {
  .workspace-page {
    grid-template-rows: auto auto auto; /* 页面布局改为三行自动高度 */
  }
  .workspace-grid {
    flex-direction: column; /* 面板改为垂直排列 */
  }
  .left-column,
  .right-column {
    width: 100% !important; /* 左右面板宽度铺满屏幕 */
  }
  .center-column {
    min-height: 360px; /* 中间区域最小高度 */
  }
  .resizer {
    display: none; /* 隐藏拖拽手柄 */
  }
}

/* 屏幕宽度 ≤960px 时（手机横屏/小平板） */
@media (max-width: 960px) {
  .workspace-header {
    flex-direction: column; /* 头部改为垂直排列 */
    align-items: stretch; /* 宽度拉伸铺满 */
  }
}
</style>