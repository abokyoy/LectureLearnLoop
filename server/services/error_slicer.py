"""错题切片服务 - 从 enhanced_practice_integration.ErrorQuestionSlicer 移植（去除 Qt 依赖）

用途：routes_bridge 的 /api/practice/slice-errors 端点从评估结果中切出错题列表。
解析逻辑与原版 1:1 保留（含新旧两代评估格式的兼容正则）。
"""

import re
from typing import Dict, List


class ErrorQuestionSlicer:
    """错题切片器 - 从完整练习结果中提取错题"""

    def __init__(self, config: dict):
        self.config = config or {}

    def slice_error_questions(self, practice_content: str, evaluation_result: str) -> List[Dict]:
        """从练习结果中切片错题

        Args:
            practice_content: 完整的练习内容（包含所有题目和用户答案）
            evaluation_result: AI评估结果

        Returns:
            错题列表，每个错题包含题目内容、用户答案、正确答案等信息
        """
        try:
            # 1. 解析评估结果，识别每题正误
            error_analysis = self._parse_error_analysis(evaluation_result)

            # 2. 优先从结构化评估报告中解析"原题/用户答案"以获得完整题干；否则回退到练习内容
            structured_questions = self._parse_questions_from_evaluation(evaluation_result)
            all_questions = structured_questions if structured_questions else self._parse_all_questions(practice_content)
            if not all_questions:
                # 若无法从 practice_content 恢复，尝试解析用户答案的简单行号映射
                answers_by_index = self._parse_user_answers_simple(practice_content)
                max_idx = max(error_analysis.keys(), default=-1)
                for i in range(max_idx + 1):
                    ua = answers_by_index.get(i, "")
                    all_questions.append({
                        "question": f"问题{i+1}",
                        "user_answer": ua
                    })

            # 3. 提取错题（以 error_analysis 为准，索引从0计）
            error_questions: List[Dict] = []
            for idx, info in sorted(error_analysis.items()):
                if not info.get("is_correct", False):
                    q_data = all_questions[idx] if 0 <= idx < len(all_questions) else {
                        "question": f"问题{idx+1}", "user_answer": "", "full_block": f"问题{idx+1}"
                    }
                    # 优先使用从评估结果中解析的完整题块，如果没有则使用题目内容
                    question_content = q_data.get("full_block", "")
                    if not question_content or question_content == f"问题{idx+1}":
                        question_content = q_data.get("question", f"问题{idx+1}")

                    error_questions.append({
                        "question_index": idx,
                        # 使用完整题块作为题目内容，包含从"原题："到分隔线的所有内容
                        "question_content": question_content,
                        "user_answer": q_data.get("user_answer", ""),
                        "correct_answer": info.get("correct_answer", ""),
                        "explanation": info.get("explanation", ""),
                        "knowledge_point_hint": info.get("knowledge_point", "")
                    })

            return error_questions

        except Exception as e:
            print(f"错题切片失败: {e}")
            return []

    def _parse_all_questions(self, practice_content: str) -> List[Dict]:
        """解析所有题目和用户答案"""
        questions = []

        # 多种解析模式
        patterns = [
            # 模式1: 题目X: ... 答案: ...
            r'题目\s*(\d+)[：:]\s*(.*?)\n.*?(?:我的)?答案[：:]\s*(.*?)(?=\n题目|\n\n|$)',
            # 模式2: X. ... 我的答案: ...
            r'(\d+)\.\s*(.*?)\n.*?我的答案[：:]\s*(.*?)(?=\n\d+\.|\n\n|$)',
            # 模式3: 问题X ... 回答: ...
            r'问题\s*(\d+)[：:]?\s*(.*?)\n.*?回答[：:]\s*(.*?)(?=\n问题|\n\n|$)',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, practice_content, re.DOTALL | re.IGNORECASE)
            if matches:
                for match in matches:
                    if len(match) >= 3:
                        questions.append({
                            "question": match[1].strip(),
                            "user_answer": match[2].strip()
                        })
                break

        # 如果没有匹配到，尝试简单分割
        if not questions:
            questions = self._simple_parse_questions(practice_content)

        return questions

    def _parse_questions_from_evaluation(self, evaluation_result: str) -> List[Dict]:
        """从结构化评估报告中解析每题块（完整原文片段）及用户答案。"""
        try:
            blocks: List[Dict] = []

            # 匹配实际的评估格式（可能没有"原题："标识符）
            pattern = r"(\d+)\.[ \t]+(.*?)(?=(?:\n----|\n\d+\.[ \t]+|\n整体评价|\Z))"

            matches = list(re.finditer(pattern, evaluation_result, re.MULTILINE | re.DOTALL))

            for m in matches:
                try:
                    idx = int(m.group(1)) - 1
                    full_content = m.group(0).strip()  # 完整的题目块
                    inner_content = m.group(2) or ""   # 原题后的内容

                    # 提取用户答案
                    ua_match = re.search(r"用户答案[：:][ \t]*([^\n]*)", full_content)
                    user_answer = ua_match.group(1).strip() if ua_match else ""

                    # 提取题目内容（从数字.后到"用户答案："前的内容）
                    question_match = re.search(r"(.*?)(?=\n用户答案[：:]|$)", inner_content, re.DOTALL)
                    if question_match:
                        question_text = question_match.group(1).strip()
                    else:
                        # 如果没有找到，使用inner_content的第一部分
                        lines = inner_content.split('\n')
                        question_lines = []
                        for line in lines:
                            if re.match(r"用户答案[：:]|判定[：:]|分析与要点[：:]", line):
                                break
                            question_lines.append(line)
                        question_text = '\n'.join(question_lines).strip()

                    blocks.append({
                        "index": idx,
                        "full_block": full_content,  # 完整的题目块，用于显示
                        "question": question_text,   # 仅题目内容，用于知识点匹配
                        "user_answer": user_answer,
                    })
                except Exception:
                    continue

            # 按索引排序，组装成顺序列表（缺失位置以空占位）
            if not blocks:
                return []
            max_idx = max(b["index"] for b in blocks)
            by_idx = {b["index"]: b for b in blocks}
            result: List[Dict] = []
            for i in range(max_idx + 1):
                b = by_idx.get(i)
                if b:
                    result.append({"question": b["question"], "user_answer": b["user_answer"], "full_block": b["full_block"]})
                else:
                    result.append({"question": f"问题{i+1}", "user_answer": "", "full_block": f"问题{i+1}"})
            return result
        except Exception:
            return []

    def _parse_user_answers_simple(self, practice_content: str) -> Dict[int, str]:
        """从 practice_content 中尽量提取 "题目和答案" 区域的按序号的用户答案映射。"""
        try:
            section = practice_content
            # 定位"题目和答案:"或其后内容
            m = re.search(r"题目和答案[:：]\s*(.*)$", practice_content, flags=re.DOTALL)
            if m:
                section = m.group(1)

            answers_by_index: Dict[int, str] = {}
            lines = [ln.strip() for ln in section.splitlines() if ln.strip()]
            for ln in lines:
                # 匹配形如 "1.", "1、", "1:" 作为题号开头
                mm = re.match(r"^(\d+)[\.、:：]?\s*(.*)$", ln)
                if mm:
                    idx = int(mm.group(1)) - 1
                    val = mm.group(2).strip()
                    # 累积（多行情况）
                    prev = answers_by_index.get(idx, "")
                    answers_by_index[idx] = (prev + " " + val).strip() if prev else val
            return answers_by_index
        except Exception:
            return {}

    def _simple_parse_questions(self, content: str) -> List[Dict]:
        """简单解析题目（兜底方案）"""
        questions = []
        lines = content.split('\n')
        current_question = ""
        current_answer = ""
        in_answer = False

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if re.match(r'^\d+[\.、]', line) or '题目' in line or '问题' in line:
                if current_question and current_answer:
                    questions.append({
                        "question": current_question,
                        "user_answer": current_answer
                    })
                current_question = line
                current_answer = ""
                in_answer = False
            elif '答案' in line or '回答' in line or in_answer:
                in_answer = True
                if '答案' in line or '回答' in line:
                    current_answer = line.split(':', 1)[-1].split('：', 1)[-1].strip()
                else:
                    current_answer += " " + line

        if current_question and current_answer:
            questions.append({
                "question": current_question,
                "user_answer": current_answer
            })

        return questions

    def _parse_error_analysis(self, evaluation_result: str) -> Dict[int, Dict]:
        """解析评估结果中的错题分析"""
        error_analysis: Dict[int, Dict] = {}

        # 先尝试解析新格式：按"原题/用户答案/判定/分析与要点"结构
        try:
            pattern = r"(?ms)^\s*(\d+)\.[ \t]*原题[：:][ \t]*\n?(.*?)(?:\n选项[：:].*?)?\n用户答案[：:][ \t]*(.*?)\n判定[：:][ \t]*([^\n]+)\n(?:分析与要点[：:][ \t]*(.*?))?(?=(?:\n----|\n\d+\.|\n整体评价|$))"
            matches = re.findall(pattern, evaluation_result)
            for m in matches:
                try:
                    idx = int(m[0]) - 1
                    verdict = (m[3] or "").strip()
                    analysis_text = (m[4] or "").strip()
                    text_norm = (verdict + " " + analysis_text).replace('\n', ' ')
                    wrong_keywords = ['错误', '不正确', '答错', '×']
                    right_keywords = ['正确', '答对', '✓']
                    unknown_keywords = ['无法评估', '无法判断', '无法确定']

                    is_unknown = any(kw in verdict for kw in unknown_keywords)
                    is_wrong = any(kw in verdict for kw in wrong_keywords)
                    is_right = (not is_wrong) and any(kw in verdict for kw in right_keywords)
                    if is_unknown:
                        continue
                    is_correct = bool(is_right)

                    # 尝试在分析中抽取正确答案
                    correct_answer = ""
                    for cp in [r'正确答案[是为：:]\s*([^\n。]+)', r'应该[是为：:]\s*([^\n。]+)', r'答案[是为：:]\s*([^\n。]+)']:
                        ca = re.search(cp, analysis_text)
                        if ca:
                            correct_answer = ca.group(1).strip()
                            break

                    # 知识点提示提取
                    knowledge_point = ""
                    for kp in [r'知识点[：:]\s*([^\n。]+)', r'涉及[：:]\s*([^\n。]+)', r'考查[：:]\s*([^\n。]+)']:
                        kpm = re.search(kp, analysis_text)
                        if kpm:
                            knowledge_point = kpm.group(1).strip()
                            break

                    error_analysis[idx] = {
                        "is_correct": is_correct,
                        "correct_answer": correct_answer,
                        "explanation": analysis_text if analysis_text else verdict,
                        "knowledge_point": knowledge_point
                    }
                except Exception:
                    continue
        except Exception:
            pass

        # 兼容旧格式：题目X/第X题/X.
        if not error_analysis:
            patterns = [
                r'题目\s*(\d+)[：:]\s*(.*?)(?=题目\s*\d+|$)',
                r'第\s*(\d+)\s*题[：:]\s*(.*?)(?=第\s*\d+\s*题|$)',
                r'(\d+)\.\s*(.*?)(?=\d+\.|$)',
            ]
            for pattern in patterns:
                matches = re.findall(pattern, evaluation_result, re.DOTALL | re.IGNORECASE)
                for match in matches:
                    try:
                        question_num = int(match[0]) - 1
                        analysis_text = match[1].strip()
                        text_norm = analysis_text.replace('\n', ' ')
                        wrong_keywords = ['错误', '不正确', '答错', '×']
                        right_keywords = ['正确', '答对', '✓']
                        unknown_keywords = ['无法评估', '无法判断', '无法确定']
                        is_unknown = any(kw in text_norm for kw in unknown_keywords)
                        is_wrong = any(kw in text_norm for kw in wrong_keywords)
                        is_right = (not is_wrong) and any(kw in text_norm for kw in right_keywords)
                        if is_unknown:
                            continue
                        is_correct = bool(is_right)

                        correct_answer = ""
                        for cp in [r'正确答案[是为：:]\s*([^\n。]+)', r'应该[是为：:]\s*([^\n。]+)', r'答案[是为：:]\s*([^\n。]+)']:
                            ca_match = re.search(cp, analysis_text)
                            if ca_match:
                                correct_answer = ca_match.group(1).strip()
                                break
                        knowledge_point = ""
                        for kp in [r'知识点[：:]\s*([^\n。]+)', r'涉及[：:]\s*([^\n。]+)', r'考查[：:]\s*([^\n。]+)']:
                            kp_match = re.search(kp, analysis_text)
                            if kp_match:
                                knowledge_point = kp_match.group(1).strip()
                                break
                        error_analysis[question_num] = {
                            "is_correct": is_correct,
                            "correct_answer": correct_answer,
                            "explanation": analysis_text,
                            "knowledge_point": knowledge_point
                        }
                    except Exception:
                        continue

        return error_analysis
