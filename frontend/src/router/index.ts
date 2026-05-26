import { createRouter, createWebHistory } from 'vue-router'
import { pinia } from '@/stores'
import { useUserStore } from '@/stores/userStore'
import LoginView from '@/views/LoginView.vue'
import ProjectListView from '@/views/ProjectListView.vue'
import WorkspaceView from '@/views/WorkspaceView.vue'
import AdminDashboard from '@/views/AdminDashboard.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/projects' },
    { path: '/login', component: LoginView, meta: { public: true } },
    { path: '/projects', component: ProjectListView, meta: { requiresAuth: true } },
    { path: '/workspace/:projectId', component: WorkspaceView, meta: { requiresAuth: true } },
    { path: '/admin', component: AdminDashboard, meta: { requiresAuth: true, role: 'admin' } },
  ],
})

router.beforeEach((to) => {
  const userStore = useUserStore(pinia)
  userStore.hydrate()

  if (to.meta.public) {
    if (userStore.isAuthenticated && to.path === '/login') {
      return userStore.isAdmin ? '/admin' : '/projects'
    }
    return true
  }

  if (!userStore.isAuthenticated) {
    return '/login'
  }

  if (to.meta.role === 'admin' && !userStore.isAdmin) {
    return '/projects'
  }

  return true
})

export default router
