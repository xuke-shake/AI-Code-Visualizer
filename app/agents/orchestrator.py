from dataclasses import dataclass
from app.tools.mermaid_validator import validate_mermaid
from app.agents.llm_provider import LLMProvider
from app.agents.prompts import MERMAID_SYSTEM_PROMPT, MERMAID_USER_TEMPLATE
from app.agents.retrieval import simple_code_retrieval
import os
import time
@dataclass
class AgentResult:
    mermaid_code: str
    node_mapping: dict
    agent_logs: list[dict]


class AgentOrchestrator:
    """固定流水线多Agent占位实现。

    后续可替换为LangGraph或真实LLM调用。这里先保证图表接口返回可渲染Mermaid。
    """

    def __init__(self):
        # 初始化我们在第一步封装的大模型提供者
        self.llm = LLMProvider()

    def _get_fallback_mermaid(self, title: str) -> str:
        """兜底输出：当 LLM 失败或语法错误时返回示例"""
        return f"""flowchart TD
        A["分析失败: {title}"] --> B["原因: LLM 响应异常或语法校验未通过"]
        B --> C["提示: 请检查后台日志或精简您的 Prompt 重新输入"]
    """

    def run_analysis(self, project_name: str, prompt: str, diagram_type: str = "flowchart") -> AgentResult:
        #TODO 这里先暂时让agent读取本地（就这个文件）
        # 等后续源码解析负责人把“ZIP解压和文件保存”做好之后，
        # 会把 PROJECT_ROOT_PATH 环境变量或者参数改掉。
        project_path = os.getenv("PROJECT_ROOT_PATH", ".")
        title = prompt.strip().replace('"', "'")[:40]

        agent_logs = []  # 用来收集各个 Agent 步骤的详细运行数据

        # ==========================================
        # 1. 【检索阶段】RetrievalAgent
        # ==========================================
        start_time = time.time()
        search_keyword = prompt[:20].strip()

        code_context = simple_code_retrieval(project_path, search_keyword)

        retrieval_duration = time.time() - start_time
        agent_logs.append({
            "agent_name": "RetrievalAgent",
            "input_summary": f"项目名: {project_name}, 关键词: {search_keyword}",
            "output_summary": f"检索完成，捞出相关上下文长度: {len(code_context)} 字符",
            "duration_sec": round(retrieval_duration, 3),
            "errors": None
        })

        # ==========================================
        # 2. 【生成阶段】DiagramAgent
        # ==========================================
        start_time = time.time()
        user_content = MERMAID_USER_TEMPLATE.format(
            project_name=project_name,
            user_prompt=prompt,
            code_context=code_context
        )

        llm_error = None
        try:
            mermaid_code = self.llm.chat(
                system_prompt=MERMAID_SYSTEM_PROMPT,
                user_prompt=user_content
            )
        except Exception as e:
            llm_error = str(e)
            print(f"LLM 报错，触发第一层兜底: {llm_error}")
            mermaid_code = self._get_fallback_mermaid(title, error_msg="LLM调用失败")

        diagram_duration = time.time() - start_time
        agent_logs.append({
            "agent_name": "DiagramAgent",
            "input_summary": f"Prompt长度: {len(user_content)}",
            "output_summary": f"Mermaid源码生成完成，长度: {len(mermaid_code)}",
            "duration_sec": round(diagram_duration, 3),
            "errors": llm_error
        })

        # ==========================================
        # 3. 【校验阶段】ReviewAgent
        # ==========================================
        start_time = time.time()

        validation = validate_mermaid(mermaid_code)
        review_error = None

        if not validation.valid:
            review_error = ";".join(validation.errors)
            print(f"Mermaid 语法校验失败: {review_error}。触发第二层兜底。")
            mermaid_code = self._get_fallback_mermaid(title, error_msg="Mermaid语法错误")
            validation = validate_mermaid(mermaid_code)  # 再次确保兜底图合法

        review_duration = time.time() - start_time
        agent_logs.append({
            "agent_name": "ReviewAgent",
            "input_summary": "待校验的 Mermaid 文本",
            "output_summary": "校验通过" if validation.valid else "校验失败，已强制转换为兜底提示图",
            "duration_sec": round(review_duration, 3),
            "errors": review_error
        })

        # ==========================================
        # 4. 【映射阶段】NodeMapping（暂时占位）
        # ==========================================
        mapping = {
            "A": {"file_path": "待后续精准符号解析接入", "start_line": 1, "end_line": 1, "symbol": "dynamic_node"}
        }

        # 返回完美的 AgentResult，前端可以直接拿到标准的 agent_logs 去展示耗时和错误了！
        return AgentResult(mermaid_code=mermaid_code, node_mapping=mapping, agent_logs=agent_logs)