<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import StatCard from '@/components/StatCard.vue'
import { useProjectStore } from '@/stores/projectStore'
import { useUserStore } from '@/stores/userStore'
import { formatDateTime, getProjectStatusLabel } from '@/utils/format'
import type { ProjectItem } from '@/types'

const router = useRouter()
const userStore = useUserStore()
const projectStore = useProjectStore()
const keyword = ref('')
const dialogVisible = ref(false)
const editingId = ref('')
const selectedProjectIds = ref<Set<string>>(new Set())
const selectedZipFile = ref<File | null>(null)
const zipFileInputRef = ref<HTMLInputElement | null>(null)

const form = reactive({
  name: '',
  description: '',
  sourceType: 'git' as 'git' | 'zip',
  repoUrl: '',
  zipFileName: '',
})

const readyCount = computed(() => projectStore.projectList.filter((item) => item.status === 'ready').length)
const outdatedCount = computed(() => projectStore.projectList.filter((item) => item.status === 'outdated').length)
const selectedCount = computed(() => selectedProjectIds.value.size)
const hasSelectedProjects = computed(() => selectedCount.value > 0)
const selectedProjects = computed(() => projectStore.projectList.filter((p) => selectedProjectIds.value.has(p.id)))

const enterWorkspaceDisabled = computed(() => selectedCount.value !== 1)
const parseDisabled = computed(() => selectedCount.value !== 1)
const syncDisabled = computed(() => selectedCount.value === 0)
const editDisabled = computed(() => selectedCount.value !== 1)
const deleteDisabled = computed(() => selectedCount.value === 0)

function toggleProjectSelection(projectId: string): void {
  if (selectedProjectIds.value.has(projectId)) {
    selectedProjectIds.value.delete(projectId);
  } else {
    selectedProjectIds.value.add(projectId);
  }
}

function handleDoubleClick(project: ProjectItem): void {
  router.push(`/workspace/${project.id}`);
}

function selectAllProjects(): void {
  projectStore.projectList.forEach((p) => selectedProjectIds.value.add(p.id))
}

function clearSelection(): void {
  selectedProjectIds.value.clear()
}

function openCreateDialog(): void {
  editingId.value = ''
  form.name = ''
  form.description = ''
  form.sourceType = 'git'
  form.repoUrl = ''
  form.zipFileName = ''
  selectedZipFile.value = null
  dialogVisible.value = true
}

function handleZipFileSelect(event: Event): void {
  const target = event.target as HTMLInputElement
  if (target.files && target.files.length > 0) {
    selectedZipFile.value = target.files[0]
    form.zipFileName = target.files[0].name
  }
}

function triggerZipFileSelect(): void {
  zipFileInputRef.value?.click()
}

function openEditDialog(project?: ProjectItem): void {
  const projectToEdit = project || selectedProjects.value[0]
  if (projectToEdit) {
    editingId.value = projectToEdit.id
    form.name = projectToEdit.name
    form.description = projectToEdit.description
    form.sourceType = projectToEdit.sourceType
    form.repoUrl = projectToEdit.repoUrl ?? ''
    form.zipFileName = ''
  }
  dialogVisible.value = true
}

async function submitProject(): Promise<void> {
  if (editingId.value) {
    await projectStore.updateProject(editingId.value, {
      name: form.name,
      description: form.description,
      repoUrl: form.repoUrl,
    })
  } else {
    await projectStore.createProject({
  ...form,
  zipFile: selectedZipFile.value,
})
  }
  dialogVisible.value = false
}

async function searchProjects(): Promise<void> {
  await projectStore.fetchProjects(keyword.value, 1)
  selectedProjectIds.value.clear()
}

async function changePage(offset: number): Promise<void> {
  const next = projectStore.pagination.page + offset
  if (next < 1) return
  const maxPage = Math.ceil(projectStore.pagination.total / projectStore.pagination.pageSize)
  if (next > maxPage) return
  await projectStore.fetchProjects(keyword.value, next)
  selectedProjectIds.value.clear()
}

async function handleEnterWorkspace(): Promise<void> {
  if (selectedProjects.value.length === 1) {
    await projectStore.selectProject(selectedProjects.value[0].id)
    router.push(`/workspace/${selectedProjects.value[0].id}`)
  }
}

async function handleParse(): Promise<void> {
  if (selectedProjects.value.length === 1) {
    projectStore.currentProject = selectedProjects.value[0]
    await projectStore.parseCurrentProject()
    await projectStore.fetchProjects(keyword.value)
  }
}

async function handleSync(): Promise<void> {
  for (const project of selectedProjects.value) {
    projectStore.currentProject = project
    await projectStore.syncCurrentProject()
  }
  await projectStore.fetchProjects(keyword.value)
}

async function handleDelete(): Promise<void> {
  const idsToDelete = Array.from(selectedProjectIds.value)
  await projectStore.removeProjects(idsToDelete)
  selectedProjectIds.value.clear()
}

function logout(): void {
  userStore.logout()
  router.push('/login')
}

onMounted(async () => {
  userStore.hydrate()
  await projectStore.fetchProjects()
})
</script>

<template>
  <main class="page-shell project-page">
    <header class="page-card page-header">
      <div class="header-left">
        <span class="badge">资源管理器</span>
        <div>
          <h1>项目</h1>
          <p class="muted">欢迎，{{ userStore.user?.username }} · 管理仓库、同步代码与进入工作台</p>
        </div>
      </div>
      <div class="toolbar">
        <button v-if="userStore.isAdmin" class="btn-secondary" @click="router.push('/admin')">管理员后台</button>
        <button class="btn-primary" @click="openCreateDialog">新建项目</button>
        <button class="btn-secondary" @click="logout">退出</button>
      </div>
    </header>

    <section class="grid-3 stats-row">
      <StatCard title="项目总数" :value="projectStore.pagination.total" caption="分页与搜索" />
      <StatCard title="已就绪" :value="readyCount" caption="可进入工作台" />
      <StatCard title="待刷新" :value="outdatedCount" caption="同步后重建图表" />
    </section>

    <section class="page-card content-card">
      <div class="toolbar top-tools">
        <input v-model="keyword" placeholder="搜索项目名称或描述" @keyup.enter="searchProjects" />
        <button class="btn-secondary" @click="searchProjects">搜索</button>
        <button class="btn-secondary" @click="projectStore.fetchProjects(keyword)">刷新</button>
        <div class="selection-actions">
          <button class="btn-secondary" @click="selectAllProjects">全选</button>
          <button class="btn-secondary" @click="clearSelection">取消</button>
        </div>
      </div>

      <div v-if="projectStore.hasProjects" class="project-list">
        <div v-for="project in projectStore.projectList" :key="project.id" class="project-item" @dblclick="handleDoubleClick(project)">
          <div class="project-checkbox">
            <input type="checkbox" :checked="selectedProjectIds.has(project.id)" @change="toggleProjectSelection(project.id)" @click.stop />
          </div>
          <div class="project-main">
            <div class="project-info">
              <div class="project-name-row">
                <span class="project-name">{{ project.name }}</span>
                <span class="badge status-badge">{{ getProjectStatusLabel(project.status) }}</span>
              </div>
              <p class="project-desc">{{ project.description }}</p>
            </div>
            <div class="project-meta">
              <span>来源：{{ project.sourceType === 'git' ? 'Git 仓库' : 'ZIP 上传' }}</span>
              <span>更新时间：{{ formatDateTime(project.updatedAt) }}</span>
              <span>图表：{{ project.diagramCount }}</span>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="empty-block">暂无项目，点击“新建项目”开始。</div>

      <div class="toolbar pagination-bar">
        <button class="btn-secondary" @click="changePage(-1)">上一页</button>
        <span class="muted">第 {{ projectStore.pagination.page }} / {{ Math.max(1, Math.ceil(projectStore.pagination.total / projectStore.pagination.pageSize)) }} 页</span>
        <button class="btn-secondary" @click="changePage(1)">下一页</button>
      </div>
    </section>

    <footer class="page-card bottom-toolbar">
      <div class="action-buttons">
        <button class="btn-primary" :disabled="enterWorkspaceDisabled" @click="handleEnterWorkspace">进入工作台</button>
        <button class="btn-primary" :disabled="parseDisabled" @click="handleParse">解析</button>
        <button class="btn-primary" :disabled="syncDisabled" @click="handleSync">同步</button>
        <button class="btn-primary" :disabled="editDisabled" @click="openEditDialog()">编辑</button>
        <button class="btn-primary" :disabled="deleteDisabled" @click="handleDelete">删除</button>
      </div>
      <div v-if="hasSelectedProjects" class="selection-info" >已选择 {{ selectedCount }} 个项目</div>
    </footer>

    <div v-if="dialogVisible" class="dialog-mask" @click.self="dialogVisible = false">
      <section class="page-card dialog-panel">
        <h3 class="section-title">{{ editingId ? '编辑项目' : '新建项目' }}</h3>
        <div class="form-grid">
          <label>项目名称<input v-model="form.name" placeholder="请输入项目名称" /></label>
          <label>项目描述<textarea v-model="form.description" placeholder="请输入项目描述" /></label>
          <label>接入方式
            <select v-model="form.sourceType">
              <option value="git">Git 仓库</option>
              <option value="zip">ZIP 上传</option>
            </select>
          </label>
          <label v-if="form.sourceType === 'git'">仓库地址<input v-model="form.repoUrl" placeholder="https://example.com/repo.git" /></label>
          <label v-else-if="!editingId">
            <input
              ref="zipFileInputRef"
              type="file"
              accept=".zip"
              style="display: none"
              @change="handleZipFileSelect"
            />
            选择本地 ZIP 文件
            <div class="zip-upload-area">
              <button class="btn-secondary" type="button" @click="triggerZipFileSelect">选择本地 ZIP 文件</button>
              <div v-if="selectedZipFile" class="selected-file-name">已选择: {{ selectedZipFile.name }}</div>
            </div>
          </label>
          <label v-else>ZIP 文件名<input v-model="form.zipFileName" placeholder="例如：repo.zip" /></label>
        </div>
        <div class="form-actions">
          <button class="btn-primary" @click="submitProject">保存项目</button>
          <button class="btn-secondary" @click="dialogVisible = false">取消</button>
        </div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.project-page {
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr) auto;
  gap: 4px;
}

.page-header,
.content-card,
.bottom-toolbar {
  padding: 6px 8px;
}

.page-header {
  min-height: var(--titlebar-height);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 6px;
  background: var(--bg-elevated);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 6px;
}

.page-header h1 {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
}

.page-header p {
  margin: 2px 0 0;
  font-size: 10px;
}

.stats-row {
  min-height: 0;
}

.content-card {
  min-height: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  gap: 4px;
  background: var(--bg-elevated);
  overflow: hidden;
}

.top-tools {
  display: flex;
  gap: 4px;
  align-items: center;
}

.top-tools input {
  flex: 1;
  min-width: 180px;
}

.selection-actions {
  display: flex;
  gap: 4px;
  margin-left: auto;
}

.project-list {
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.project-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  background: var(--panel-muted);
  border: 1px solid rgba(255, 255, 255, 0.04);
  cursor: pointer;
  transition: background 0.15s ease;
}

.project-item:hover {
  background: rgba(255, 255, 255, 0.04);
}

.project-checkbox {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.project-main {
  flex: 1;
  min-width: 0;
}

.project-name-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.project-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
}

.project-desc {
  margin: 2px 0 0;
  font-size: 10px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.project-meta {
  display: flex;
  gap: 12px;
  margin-top: 4px;
  color: var(--muted);
  font-size: 10px;
}

.status-badge {
  color: var(--text-soft);
}

.empty-block {
  min-height: 100px;
  display: grid;
  place-items: center;
  color: var(--muted);
  border: 1px dashed rgba(255, 255, 255, 0.08);
  border-radius: var(--radius);
  font-size: 11px;
}

.pagination-bar {
  justify-content: flex-end;
}

.bottom-toolbar {
  min-height: 36px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  background: var(--bg-elevated);
}

.action-buttons {
  display: flex;
  gap: 4px;
}

.selection-info {
  font-size: 11px;
  color: var(--muted);
}

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
  width: min(420px, 100%);
  padding: 12px;
  display: grid;
  gap: 8px;
}

.form-grid {
  display: grid;
  gap: 8px;
}

label {
  display: grid;
  gap: 4px;
  font-size: 11px;
}

.zip-upload-area {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.selected-file-name {
  color: var(--text-soft);
  font-size: 11px;
  padding: 4px 8px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: var(--radius-sm);
}

textarea {
  min-height: 60px;
}

@media (max-width: 1280px) {
  .project-page {
    grid-template-rows: auto auto auto auto;
  }

  .content-card {
    min-height: 300px;
  }
}

@media (max-width: 960px) {
  .page-header {
    flex-direction: column;
    align-items: stretch;
  }

  .header-left {
    align-items: flex-start;
  }

  .project-meta {
    flex-wrap: wrap;
    gap: 6px;
  }

  .bottom-toolbar {
    flex-direction: column;
    gap: 6px;
  }

  .action-buttons {
    flex-wrap: wrap;
    justify-content: center;
  }
}
</style>
