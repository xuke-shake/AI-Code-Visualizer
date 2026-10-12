import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { fetchCurrentUserApi, loginApi, registerApi } from '@/api/auth'
import { setAuthInvalidationHandler } from '@/api/http'
import type { LoginPayload, RegisterPayload, UserProfile } from '@/types'
import { clearStoredToken, clearStoredUser, getStoredToken, getStoredUser, setStoredToken, setStoredUser } from '@/utils/storage'
import { pinia } from '@/stores'
import { useProjectStore } from './projectStore'
import { useDiagramStore } from './diagramStore'
import { useTaskStore } from './taskStore'

export const useUserStore = defineStore('user', () => {
  const token = ref('')
  const user = ref<UserProfile | null>(null)
  const loading = ref(false)
  const initialized = ref(false)
  let sessionRevision = 0
  let hydratePromise: Promise<boolean> | null = null

  const isAuthenticated = computed(() => Boolean(token.value))
  const isAdmin = computed(() => user.value?.role === 'admin')

  async function hydrate(): Promise<boolean> {
    if (hydratePromise) return hydratePromise
    if (initialized.value) return Boolean(token.value && user.value)
    const revision = sessionRevision
    const requestedToken = getStoredToken()
    token.value = requestedToken
    user.value = getStoredUser()
    initialized.value = true
    if (!requestedToken) {
      user.value = null
      return false
    }
    hydratePromise = (async () => {
      try {
        const loaded = await fetchCurrentUserApi()
        if (sessionRevision !== revision || token.value !== requestedToken || getStoredToken() !== requestedToken) {
          return Boolean(token.value && user.value)
        }
        user.value = loaded
        setStoredUser(loaded)
        return true
      } catch {
        if (sessionRevision === revision && token.value === requestedToken && getStoredToken() === requestedToken) {
          logout()
          return false
        }
        return Boolean(token.value && user.value)
      } finally {
        hydratePromise = null
      }
    })()
    return hydratePromise
  }

  function applySession(nextToken: string, nextUser: UserProfile): void {
    sessionRevision += 1
    const changedUser = user.value?.id !== nextUser.id || token.value !== nextToken
    token.value = nextToken
    user.value = nextUser
    setStoredToken(nextToken)
    setStoredUser(nextUser)
    if (changedUser) {
      useProjectStore(pinia).reset()
      useDiagramStore(pinia).reset()
      useTaskStore(pinia).reset()
    }
  }

  async function login(payload: LoginPayload): Promise<void> {
    loading.value = true
    try {
      const session = await loginApi(payload)
      applySession(session.token, session.user)
    } finally {
      loading.value = false
    }
  }

  async function register(payload: RegisterPayload): Promise<void> {
    loading.value = true
    try {
      const session = await registerApi(payload)
      applySession(session.token, session.user)
    } finally {
      loading.value = false
    }
  }

  function logout(): void {
    sessionRevision += 1
    hydratePromise = null
    token.value = ''
    user.value = null
    clearStoredToken()
    clearStoredUser()
    useProjectStore(pinia).reset()
    useDiagramStore(pinia).reset()
    useTaskStore(pinia).reset()
  }

  setAuthInvalidationHandler(logout)

  return {
    token,
    user,
    loading,
    initialized,
    isAuthenticated,
    isAdmin,
    hydrate,
    login,
    register,
    logout,
  }
})
