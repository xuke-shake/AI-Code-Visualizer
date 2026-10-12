import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ChatPanel from './ChatPanel.vue'

describe('ChatPanel 指令边界', () => {
  it('拒绝空白指令，不触发生成事件', async () => {
    const wrapper = mount(ChatPanel, { props: { pending: false, selectedCount: 1 } })
    await wrapper.get('textarea').setValue('   ')
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('generate')).toBeUndefined()
    expect(wrapper.text()).toContain('请输入生成指令')
  })

  it('提交前去除两端空白', async () => {
    const wrapper = mount(ChatPanel, { props: { pending: false, selectedCount: 1 } })
    await wrapper.get('textarea').setValue('  生成流程图  ')
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('generate')?.[0]?.[0]).toMatchObject({ instruction: '生成流程图' })
  })
})
