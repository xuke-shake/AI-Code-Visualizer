import os

#搜索用户提问的关键词并返回给大模型
def simple_code_retrieval(project_path: str, keyword: str, max_files: int = 3) -> str:
    """
    简易源码检索函数：在指定项目中查找包含关键字的 Python 文件，并拼接成上下文

    :param project_path: 项目根目录路径
    :param keyword: 用户输入的搜索关键词（如 "OrderService" 或 "create_user"）
    :param max_files: 最多读取的文件数量，防止上下文过长撑爆大模型
    :return: 拼接好的代码文本上下文
    """
    if not keyword:
        return "没有提供检索关键词，未匹配到任何参考代码。"

    matched_chunks = []
    files_count = 0

    # 遍历项目目录
    for root, dirs, files in os.walk(project_path):
        # 忽略隐藏目录（如 .git）和虚拟环境、缓存目录
        if any(ignored in root for ignored in [".git", "__pycache__", "venv", ".pytest_cache"]):
            continue

        for file in files:
            # 暂时只检索 Python 源码文件
            if file.endswith(".py"):
                file_path = os.path.join(root, file)

                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()

                        # 核心逻辑：如果文件内容包含关键词，就捞出来
                        if keyword in content:
                            # 相对路径，方便大模型识别文件位置
                            relative_path = os.path.relpath(file_path, project_path)

                            chunk = f"--- 文件路径: {relative_path} ---\n{content}\n"
                            matched_chunks.append(chunk)

                            files_count += 1
                            if files_count >= max_files:
                                break
                except Exception as e:
                    # 容错处理，防止个别文件读取错误导致整个检索崩溃
                    print(f"读取文件失败 {file_path}: {str(e)}")
                    continue

        if files_count >= max_files:
            break

    if not matched_chunks:
        return f"在项目中未找到包含关键词 '{keyword}' 的代码片段。"

    # 将找到的所有代码块拼接成一个大字符串
    return "\n".join(matched_chunks)