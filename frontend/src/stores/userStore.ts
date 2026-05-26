import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { loginApi, registerApi } from '@/api/auth'
import type { LoginPayload, RegisterPayload, UserProfile } from '@/types'
import { clearStoredToken, clearStoredUser, getStoredToken, getStoredUser, setStoredToken, setStoredUser } from '@/utils/storage'

export const useUserStore = defineStore('user', () => {
  const token = ref('')
  const user = ref<UserProfile | null>(null)
  const loading = ref(false)
  const initialized = ref(false)

  const isAuthenticated = computed(() => Boolean(token.value))
  const isAdmin = computed(() => user.value?.role === 'admin')

  function hydrate(): void {
    if (initialized.value) return
    token.value = getStoredToken()
    user.value = getStoredUser()
    initialized.value = true
  }

  function applySession(nextToken: string, nextUser: UserProfile): void {
    token.value = nextToken
    user.value = nextUser
    setStoredToken(nextToken)
    setStoredUser(nextUser)
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
    token.value = ''
    user.value = null
    clearStoredToken()
    clearStoredUser()
  }

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
