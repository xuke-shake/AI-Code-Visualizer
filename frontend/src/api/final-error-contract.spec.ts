import { describe, expect, it, vi } from 'vitest'
import { AxiosError } from 'axios'

describe('C04/C16: trackable generation failures', () => {
  it('keeps the public failed task id through the HTTP error boundary', async () => {
    vi.stubEnv('VITE_ENABLE_MOCK', 'false')
    const { http, requestData } = await import('./http')
    http.defaults.adapter = async (config) => {
      throw new AxiosError('local failure', 'ERR_BAD_RESPONSE', config, null, {
        config, status: 500, statusText: 'Internal Server Error', headers: {},
        data: { code: 50000, message: '服务器内部错误', data: { task_id: 9 } },
      })
    }
    await expect(requestData({ method: 'post', url: '/api/projects/1/analysis' })).rejects.toMatchObject({ message: '服务器内部错误', status: 500, taskId: 9 })
    vi.unstubAllEnvs()
  })
})
