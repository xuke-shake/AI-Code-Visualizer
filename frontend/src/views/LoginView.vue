<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/userStore'

const router = useRouter()
const userStore = useUserStore()
const isRegister = ref(false)
const errorMessage = ref('')

const form = reactive({
  username: '',
  email: 'user@demo',
  password: 'user123',
})

async function submit(): Promise<void> {
  errorMessage.value = ''
  try {
    if (isRegister.value) {
      await userStore.register(form)
    } else {
      await userStore.login({ email: form.email, password: form.password })
    }
    await router.push(userStore.isAdmin ? '/admin' : '/projects')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登录失败'
  }
}
</script>

<template>
  <main class="login-page">
    <div class="login-shell">
      <header class="login-brand">
        <div class="brand-mark">A</div>
        <div>
          <strong>AI Flow Visualizer</strong>
          <p>基于 AI 实现仓库业务流程可视化平台</p>
        </div>
      </header>

      <section class="login-panel">
        <h1 class="login-title">{{ isRegister ? '创建账户' : '登录' }}</h1>

        <div class="form-grid">
          <div v-if="isRegister" class="form-group">
            <label class="form-label">用户名</label>
            <input v-model="form.username" class="form-input" placeholder="请输入用户名" />
          </div>
          <div class="form-group">
            <label class="form-label">邮箱地址</label>
            <input  v-model="form.email" class="form-input" placeholder="请输入邮箱" />
          </div>
          <div class="form-group">
            <label class="form-label">密码</label>
            <input  v-model="form.password" class="form-input" type="password" placeholder="请输入密码" />
          </div>
        </div>

        <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>

        <button class="submit-btn" :disabled="userStore.loading" @click="submit">
          {{ userStore.loading ? '提交中...' : isRegister ? '创建账户' : '登录' }}
        </button>
      </section>

      <section class="login-switcher">
        <p>
          {{ isRegister ? '已有账号？' : '新用户？' }}
          <a href="#" @click.prevent="isRegister = !isRegister">
            {{ isRegister ? '立即登录' : '创建一个账号' }}
          </a>
        </p>
      </section>

    </div>
  </main>
</template>

<style scoped>
.login-page {
  height: 100vh;
  overflow: auto;
  display: grid;
  place-items: center;
  padding: 24px 16px;
  background: #f6f8fa;
  color: #1f2328;
}

.login-shell {
  width: min(320px, 100%);
  display: grid;
  gap: 16px;
}

.login-brand {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  text-align: left;
}

.brand-mark {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  display: grid;
  place-items: center;
  background: #24292f;
  color: #ffffff;
  font-weight: 700;
  font-size: 16px;
}

.login-brand strong {
  display: block;
  font-size: 13px;
}

.login-brand p {
  margin: 2px 0 0;
  font-size: 11px;
  color: #57606a;
}

.login-panel {
  border: 1px solid #d0d7de;
  border-radius: 6px;
  background: #ffffff;
  padding: 16px;
  display: grid;
  gap: 12px;
}

.login-title {
  margin: 0;
  font-size: 16px;
  font-weight: 400;
  text-align: center;
}

.form-grid {
  display: grid;
  gap: 12px;
}

.form-group {
  display: grid;
  gap: 6px;
}

.form-label {
  font-size: 12px;
  font-weight: 400;
}

.form-input {
  width: 100%;
  padding: 5px 8px;
  border: 1px solid #d0d7de;
  border-radius: 6px;
  background: #ffffff;
  color: #1f2328;
  font-size: 12px;
  line-height: 1.5;
}

.form-input:focus {
  border-color: #0969da;
  outline: none;
  box-shadow: 0 0 0 3px rgba(9, 105, 218, 0.12);
}

.submit-btn {
  width: 100%;
  padding: 6px 12px;
  border: none;
  border-radius: 6px;
  background: #1f883d;
  color: #ffffff;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
}

.submit-btn:hover:not(:disabled) {
  background: #1a7f37;
}

.submit-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.error-text {
  margin: 0;
  color: #cf222e;
  font-size: 11px;
  padding: 8px;
  background: rgba(207, 34, 46, 0.06);
  border-radius: 6px;
  border: 1px solid rgba(207, 34, 46, 0.15);
}

.login-switcher {
  border: 1px solid #d0d7de;
  border-radius: 6px;
  padding: 12px;
  text-align: center;
  background: #ffffff;
}

.login-switcher p {
  margin: 0;
  font-size: 12px;
  color: #1f2328;
}

.login-switcher a {
  color: #0969da;
  text-decoration: none;
}

.login-switcher a:hover {
  text-decoration: underline;
}


.login-note h3 {
  margin: 0;
  font-size: 11px;
  font-weight: 600;
  color: #57606a;
}

.login-note div {
  display: grid;
  gap: 2px;
}

.login-note span {
  font-size: 11px;
  color: #57606a;
}

.login-note code {
  font-size: 11px;
  font-family: ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, Liberation Mono, monospace;
  padding: 4px 8px;
  background: #f6f8fa;
  border-radius: 4px;
  color: #1f2328;
}
</style>
