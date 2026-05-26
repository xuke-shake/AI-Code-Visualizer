import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ProgressBar from './ProgressBar.vue'

describe('ProgressBar', () => {
  it('展示当前进度和历史消息', () => {
    const wrapper = mount(ProgressBar, {
      props: {
        socketStatus: 'connected',
        task: {
          projectId: 'p1',
          taskId: 't1',
          type: 'diagram',
          progress: 68,
          status: 'running',
          message: '正在生成图表',
          updatedAt: '2026-05-11T12:00:00.000Z',
        },
        history: [
          {
            projectId: 'p1',
            taskId: 't1',
            type: 'diagram',
            progress: 68,
            status: 'running',
            message: '正在生成图表',
            updatedAt: '2026-05-11T12:00:00.000Z',
          },
        ],
      },
    })

    expect(wrapper.text()).toContain('68%')
    expect(wrapper.text()).toContain('正在生成图表')
  })
})
