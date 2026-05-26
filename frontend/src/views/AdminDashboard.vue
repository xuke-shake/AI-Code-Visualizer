<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { fetchAdminOverviewApi, fetchAdminTasksApi, fetchAdminUsersApi } from '@/api/admin'
import StatCard from '@/components/StatCard.vue'
import { useUserStore } from '@/stores/userStore'
import { formatDateTime, getRoleLabel } from '@/utils/format'
import type { AdminOverview, AdminUserItem, TaskProgressEvent } from '@/types'

const router = useRouter()
const userStore = useUserStore()
const overview = ref<AdminOverview | null>(null)
const users = ref<AdminUserItem[]>([])
const tasks = ref<TaskProgressEvent[]>([])

async function loadAdminData(): Promise<void> {
  overview.value = await fetchAdminOverviewApi()
  users.value = await fetchAdminUsersApi()
  tasks.value = await fetchAdminTasksApi()
}

function logout(): void {
  userStore.logout()
  router.push('/login')
}

onMounted(loadAdminData)
</script>

<template>
  <main class="page-shell admin-page">
    <header class="page-card admin-header">
      <div class="header-left">
        <span class="badge">监控面板</span>
        <div>
          <h1>管理员后台</h1>
          <p class="muted">查看用户、项目与任务运行状态</p>
        </div>
      </div>
      <div class="toolbar">
        <button class="btn-secondary" @click="router.push('/projects')">项目列表</button>
        <button class="btn-secondary" @click="loadAdminData">刷新</button>
        <button class="btn-secondary" @click="logout">退出</button>
      </div>
    </header>

    <section class="grid-4 stats-row">
      <StatCard title="用户数" :value="overview?.userCount || 0" caption="平台注册用户" />
      <StatCard title="项目数" :value="overview?.projectCount || 0" caption="全部仓库项目" />
      <StatCard title="任务数" :value="overview?.taskCount || 0" caption="累计任务" />
      <StatCard title="成功率" :value="`${overview?.successRate || 0}%`" caption="执行完成率" />
    </section>

    <section class="admin-content grid-2">
      <div class="page-card table-card">
        <div class="app-panel-title">
          <div>
            <h3 class="section-title">用户列表</h3>
            <p class="muted">角色、项目数量与最近活跃时间</p>
          </div>
        </div>
        <div class="table-shell">
          <table>
            <thead>
              <tr>
                <th>用户</th>
                <th>角色</th>
                <th>项目数</th>
                <th>最近活跃</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in users" :key="item.id">
                <td>{{ item.username }}<br /><span class="muted">{{ item.email }}</span></td>
                <td>{{ getRoleLabel(item.role) }}</td>
                <td>{{ item.projectCount }}</td>
                <td>{{ formatDateTime(item.lastActiveAt) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="page-card table-card">
        <div class="app-panel-title">
          <div>
            <h3 class="section-title">任务监控</h3>
            <p class="muted">最近任务状态、进度与时间</p>
          </div>
        </div>
        <div class="table-shell">
          <table>
            <thead>
              <tr>
                <th>类型</th>
                <th>状态</th>
                <th>进度</th>
                <th>时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in tasks.slice(0, 8)" :key="`${item.taskId}-${item.updatedAt}`">
                <td>{{ item.type }}</td>
                <td>{{ item.status }}</td>
                <td>{{ item.progress }}%</td>
                <td>{{ formatDateTime(item.updatedAt) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  </main>
</template>

<style scoped>
.admin-page {
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 4px;
}

.admin-header,
.table-card {
  padding: 6px 8px;
}

.admin-header {
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

.admin-header h1 {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
}

.admin-header p {
  margin: 1px 0 0;
  font-size: 10px;
}

.admin-content {
  min-height: 0;
}

.table-card {
  min-height: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 4px;
  background: var(--bg-elevated);
}

.app-panel-title p {
  margin: 1px 0 0;
  font-size: 10px;
}

.table-shell {
  min-height: 0;
  overflow: auto;
}

.table-shell table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}

.table-shell th,
.table-shell td {
  text-align: left;
  padding: 4px 6px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  vertical-align: top;
}

.table-shell th {
  position: sticky;
  top: 0;
  background: var(--bg-elevated);
}

@media (max-width: 1280px) {
  .admin-page {
    grid-template-rows: auto auto auto;
  }

  .admin-content {
    min-height: 360px;
  }
}

@media (max-width: 960px) {
  .admin-header {
    flex-direction: column;
    align-items: stretch;
  }

  .header-left {
    align-items: flex-start;
  }
}
</style>

