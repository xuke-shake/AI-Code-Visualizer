
import unittest
import os
from app.agents.orchestrator import AgentOrchestrator


class TestAgentOrchestrator(unittest.TestCase):

    def setUp(self):
        #TODO填入你的真实 Key
        os.environ["LLM_API_KEY"] = "ark-d36bbb42-8d4b-4256-9599-bf570da3e58a-72b7c"
        os.environ["LLM_BASE_URL"] = "https://ark.cn-beijing.volces.com/api/v3"

        self.orchestrator = AgentOrchestrator()
        self.project_name = "TestProject"

    def test_agent_analysis_flow(self):
        """测试完整的：源码检索 -> LLM生成 -> 语法校验 流程"""
        # 故意带有关键字 "AgentOrchestrator"，迫使检索器去捞取真实代码
        prompt = "我想看 AgentOrchestrator 的核心类和分析流程"

        # 运行被测函数
        result = self.orchestrator.run_analysis(
            project_name=self.project_name,
            prompt=prompt
        )

        # --- 自动化断言验证 ---
        # 1. 验证返回的数据结构不为空
        self.assertIsNotNone(result.mermaid_code)
        self.assertIsInstance(result.agent_logs, list)

        # 2. 验证三个关键 Agent 的日志都存在
        agent_names = [log["agent_name"] for log in result.agent_logs]
        self.assertIn("RetrievalAgent", agent_names)
        self.assertIn("DiagramAgent", agent_names)
        self.assertIn("ReviewAgent", agent_names)

        # --- 打印出来供人工检查 ---
        print("\n" + "=" * 60)
        print("🟢 [unittest 打印结果] Mermaid 图表生成成功:")
        print("=" * 60)
        print(result.mermaid_code)
        print("=" * 60)

        print("\n⏱️ 各个 Agent 耗时与状态:")
        for log in result.agent_logs:
            print(f"- {log['agent_name']}: {log['duration_sec']} 秒 | 错误: {log['errors']}")


if __name__ == '__main__':
    unittest.main()