# agent_core.py
# Agent Reasoning Engine
# ReAct (Reason + Act) pattern with planning, tool composition, and self-correction

"""
DesignAgent — ReAct Reasoning Engine (Enhanced)

Workflow:
    user goal → [Planning] → Thought → Action → Observation → ... → Final Answer

Enhancements over base ReAct:
    - Planning phase: generates execution plan before tool calls
    - Nested JSON parsing: bracket-counting parser for complex tool args
    - Tool result caching: avoids redundant computation within a run
    - Tool composition (pipeline): sequential multi-tool execution in one step
    - Format retry: auto-corrects malformed LLM output (1 retry)
    - Clarification: agent can ask user for missing information
    - Confidence scoring: final answer includes reliability estimate
"""

import re
import json
import time
import logging
import threading
from dataclasses import dataclass, field
from typing import Optional, Any

from llm_helper import LLMHelper

logger = logging.getLogger(__name__)


# ==============================================================================
# Timeout Protection
# ==============================================================================

class TimeoutError(Exception):
    """Timeout exception"""
    pass


def run_with_timeout(func, args=(), kwargs={}, timeout_seconds=10):
    """
    Execute function within time limit, raise on timeout.
    Uses threading for Windows compatibility.
    """
    result = []
    exception = []

    def target():
        try:
            result.append(func(*args, **kwargs))
        except Exception as e:
            exception.append(e)

    thread = threading.Thread(target=target)
    thread.daemon = True
    thread.start()
    thread.join(timeout_seconds)

    if thread.is_alive():
        raise TimeoutError(f"操作超时 ({timeout_seconds}秒)")

    if exception:
        raise exception[0]

    return result[0]

# ==============================================================================
# Data Classes (Enhanced: clarification + confidence)
# ==============================================================================

@dataclass
class AgentStep:
    """One step in the agent reasoning process"""
    step_num: int
    thought: str
    action: Optional[str] = None
    observation: Optional[str] = None
    cached: bool = False  # whether result came from cache

    def format_display(self) -> str:
        """Format for user-readable display"""
        parts = [f"Step {self.step_num}: {self.thought}"]
        if self.action:
            cache_tag = " (cached)" if self.cached else ""
            parts.append(f"  🔧 {self.action}{cache_tag}")
        if self.observation:
            obs = self.observation
            if len(obs) > 200:
                obs = obs[:200] + "..."
            parts.append(f"  📋 {obs}")
        return "\n".join(parts)


@dataclass
class AgentResult:
    """Final result of agent reasoning (enhanced)"""
    answer: str
    scratchpad: list[AgentStep] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    iterations: int = 0
    confidence: str = ""  # "high" / "medium" / "low"
    needs_clarification: bool = False  # whether agent needs more info from user
    clarification_question: str = ""  # the question to ask user

    def get_scratchpad_text(self) -> str:
        """Get plain text display of reasoning process"""
        if not self.scratchpad:
            return ""
        lines = ["📋 推理过程:"]
        for step in self.scratchpad:
            lines.append(step.format_display())
        return "\n".join(lines)

# ==============================================================================
# ReAct System Prompt (Enhanced: planning, clarification, pipeline, confidence)
# ==============================================================================

REACT_SYSTEM_PROMPT = """你是一个专业的 CIC 滤波器设计验证 Agent。你可以通过调用工具来分析和验证设计。

## 核心知识
- CIC = 级联积分梳状滤波器 (Cascaded Integrator-Comb)
- 位宽增长公式: N * ceil(log2(R * M))
- 阻带抑制: ≈ N * 13dB
- FIR 补偿滤波器用于修正通带衰减 (droop)

## 可用工具
{tools_description}

## 输出格式规则

你必须严格按以下格式之一输出。每次只输出一步。

### 格式A: 需要调用工具时
```
Thought: (你的推理，解释为什么要调用这个工具)
Action: tool_name({{"param1": value1, "param2": value2}})
```

### 格式B: 需要按顺序调用多个工具时 (pipeline)
```
Thought: (解释为什么需要依次调用这些工具)
Action: pipeline([tool_a({{"p1": v1}}), tool_b({{"p2": v2}})])
```

### 格式C: 已有足够信息，给出最终回答时
```
Thought: (总结你的推理过程)
Confidence: high|medium|low
Final Answer: (给用户的完整回答，使用中文，结构清晰)
```

### 格式D: 信息不足，需要向用户追问时
```
Thought: (说明缺少什么信息)
Clarification: (用中文向用户提出具体问题)
```

## 重要规则
1. 每次只输出一个 Thought + Action 或 Thought + Final Answer 或 Thought + Clarification
2. Action 中的参数必须是合法 JSON
3. 如果用户的问题不需要工具就能回答，直接用 Final Answer
4. **强制规划 (Planner)**: 遇到复杂设计目标（如参数推荐）时，请先输出你的整体规划 (`Thought: Plan: 1... 2...`)。
5. **自我纠错 (Self-Reflection)**: 如果工具返回了错误、警告、或不满足最佳实践指标（如通带衰减大于0.5dB，或FPGA资源爆炸），你**必须**在下一步的 Thought 中写出 `"Self-Reflection: ..."` 分析原因，并主动调整参数重试。
6. 回答使用中文，专业术语保留英文
7. 在 Final Answer 中，要引用工具的具体数值结果，而不是泛泛而谈
8. 当工具返回包含 "script"、"code" 等字段的结果时，你必须在 Final Answer 中用 ``` 代码块完整展示代码内容。如果代码过长也必须完整展示，不要截断。
9. **置信度 (Confidence)**: 在给出 Final Answer 前，必须标注 `Confidence: high|medium|low`。high = 工具验证通过且指标优秀; medium = 部分指标有妥协; low = 缺少关键验证或存在已知风险。
10. **追问 (Clarification)**: 当用户需求模糊（如缺少采样率、目标平台等关键信息）时，使用 Clarification 格式向用户提问，不要猜测。
11. **工具编排 (Pipeline)**: 当需要依次调用多个工具且后续工具不依赖前序结果时，使用 pipeline 格式一次性提交。
12. **设计参数推荐输出**: 当用户需求涉及参数推荐（出现采样率、带宽、抽取比、插值比、纹波、阻带衰减等关键词），必须按以下工作流执行:
    a. 先调用 `suggest_design_params({{"description": "<用户原话或精简版>"}})` 取得候选参数
    b. 再调用 `check_param_constraints` 校验，`simulate_freq_response` 评估；若 valid=false 或通带 droop>0.5dB 或阻带衰减不足，必须 Self-Reflection 后再调 `suggest_design_params` 或手工调整后重验一次
    c. **即使性能指标未完全满足，只要参数本身通过 `check_param_constraints`，也必须给出一个"最佳可用候选"用于一键应用**。不要因为纹波/阻带未完全达标而拒绝输出参数。
    d. Final Answer 末尾**必须**追加一个独立的 ```json 代码块，且该代码块里**只放参数对象本身**，不要混入解释文字。键名严格限定为:
       `mode, ratio, stages, delay, fir_taps, passband_ratio, fir_type, data_width, fs_in`
       其中 mode ∈ {{Decimator, Interpolator, Decimator_FIR, Interpolator_FIR}}；fs_in 单位为 Hz (数值)。
    e. 若候选参数未完全满足性能指标，正文里必须明确写出未满足项、实测数值、以及这是"最佳可用候选"；但 **JSON 代码块仍然必须输出**，供 UI 一键应用。只有当 `check_param_constraints` 也失败时，才禁止输出该 JSON。"""

PLANNING_PROMPT = """基于用户目标，请先制定一个简洁的执行计划。

用户目标: {user_goal}

请输出你的计划，格式如下:
Plan:
1. (第一步要做什么，调用什么工具)
2. (第二步)
3. ...

若用户目标是设计参数推荐类（含采样率/带宽/抽取比/插值比/纹波/阻带衰减等关键词），推荐工作流为:
Plan:
1. suggest_design_params 取候选参数
2. check_param_constraints 校验 + simulate_freq_response 评估指标
3. 若不达标则调整参数重跑 step 2；若仍无法完全达标，则选出通过参数合法性校验的最佳可用候选，并在 Final Answer 末尾输出严格键名的 JSON 代码块供一键应用，同时正文明确说明未满足的指标与实测数值

只输出计划，不要执行任何工具调用。"""

FORMAT_CORRECTION_PROMPT = """你的上一次输出格式不正确。请严格按照以下格式之一重新输出:

格式A (调用工具):
Thought: (推理)
Action: tool_name({{"param": value}})

格式B (最终回答):
Thought: (总结)
Confidence: high|medium|low
Final Answer: (回答)

格式C (追问):
Thought: (说明)
Clarification: (问题)

你上一次的输出是:
{raw_response}

请重新输出，严格遵循格式。"""

# ==============================================================================
# Agent Engine (Enhanced)
# ==============================================================================

class DesignAgent:
    """
    ReAct-based CIC design assistant agent (enhanced).

    Enhancements:
        - Planning phase before execution
        - Tool result caching within a run
        - Pipeline (multi-tool) execution
        - Format retry on parse failure
        - Clarification support
        - Confidence scoring
    """

    MAX_ITERATIONS = 12

    def __init__(self, llm: LLMHelper, tools: list[dict], on_progress=None, on_step=None):
        self.llm = llm
        self.tools = {t["name"]: t for t in tools}
        self._tools_description = self._build_tools_description(tools)
        self.on_progress = on_progress
        self.on_step = on_step

    def _notify_progress(self, step: int, total: int, status: str):
        if self.on_progress:
            try:
                self.on_progress(step, total, status)
            except Exception:
                pass

    def _notify_step(self, step: 'AgentStep'):
        if self.on_step:
            try:
                self.on_step(step)
            except Exception:
                pass

    def run(self, user_goal: str, context_params: Optional[dict] = None) -> AgentResult:
        logger.info(f"[AGENT] ========== 开始推理任务 ==========")
        logger.info(f"[AGENT] 用户目标: {user_goal}")

        scratchpad: list[AgentStep] = []
        tools_used: list[str] = []
        recent_actions = []
        tool_cache: dict[str, str] = {}  # (1.3) cache: signature → result
        plan_text = ""

        # (2.1) Planning phase: generate execution plan for complex goals
        params_str = json.dumps(context_params, indent=2, ensure_ascii=False) if context_params else ""
        plan_text = self._generate_plan(user_goal, params_str)
        if plan_text:
            logger.info(f"[AGENT] 生成执行计划: {plan_text[:200]}")

        for step_num in range(1, self.MAX_ITERATIONS + 1):
            logger.info(f"[AGENT] ========== 步骤 {step_num}/{self.MAX_ITERATIONS} ==========")

            messages = self._build_messages(user_goal, params_str, scratchpad, plan_text)

            # Call LLM with lower temperature for format compliance
            try:
                self._notify_progress(step_num, self.MAX_ITERATIONS, "深度思考中")
                response = self.llm._call_api_with_messages(messages, temperature=0.1)
                logger.info(f"[AGENT] LLM 响应长度: {len(response)} 字符")
            except RuntimeError as e:
                logger.error(f"[AGENT] LLM 调用失败: {e}")
                return AgentResult(
                    answer=f"❌ LLM 调用失败: {e}",
                    scratchpad=scratchpad, tools_used=tools_used,
                    iterations=step_num
                )

            # Parse LLM output
            parsed = self._parse_response(response)

            # (2.2) Format retry: if parse failed, send correction prompt once
            if parsed["type"] == "unknown":
                logger.warning("[AGENT] 响应解析失败，尝试格式纠正重试")
                retry_msg = FORMAT_CORRECTION_PROMPT.format(raw_response=response[:500])
                retry_messages = messages + [
                    {"role": "assistant", "content": response},
                    {"role": "user", "content": retry_msg}
                ]
                try:
                    response = self.llm._call_api_with_messages(retry_messages, temperature=0.05)
                    parsed = self._parse_response(response)
                except RuntimeError:
                    pass

            logger.info(f"[AGENT] 解析结果类型: {parsed['type']}")

            # Handle: Final Answer
            if parsed["type"] == "final_answer":
                logger.info("[AGENT] 获得最终答案，推理结束")
                return AgentResult(
                    answer=parsed["content"],
                    scratchpad=scratchpad, tools_used=tools_used,
                    iterations=step_num,
                    confidence=parsed.get("confidence", "")
                )

            # Handle: Clarification (2.3)
            if parsed["type"] == "clarification":
                logger.info("[AGENT] Agent 请求追问用户")
                return AgentResult(
                    answer=parsed["content"],
                    scratchpad=scratchpad, tools_used=tools_used,
                    iterations=step_num,
                    needs_clarification=True,
                    clarification_question=parsed["content"]
                )

            # Handle: Tool call (single or pipeline)
            if parsed["type"] == "tool_call":
                tool_name = parsed["tool_name"]
                tool_args = parsed["tool_args"]
                tools_used.append(tool_name)

                # Circuit breaker
                action_sig = f"{tool_name}:{json.dumps(tool_args, sort_keys=True)}"
                recent_actions.append(action_sig)
                if len(recent_actions) > 6:
                    recent_actions.pop(0)

                _is_repeat = recent_actions.count(action_sig) >= 3
                _is_alternating = (
                    len(recent_actions) >= 4
                    and recent_actions[-1] == recent_actions[-3]
                    and recent_actions[-2] == recent_actions[-4]
                    and recent_actions[-1] != recent_actions[-2]
                )
                if _is_repeat or _is_alternating:
                    logger.warning(f"[AGENT] 熔断: {action_sig}")
                    return AgentResult(
                        answer=f"⚠️ 检测到重复执行相同工具，可能陷入循环。\n已执行的工具: {tools_used}\n请重新表述问题或简化需求。",
                        scratchpad=scratchpad, tools_used=tools_used,
                        iterations=step_num
                    )

                # Execute with cache
                self._notify_progress(step_num, self.MAX_ITERATIONS, f"正在调用工具: {tool_name}...")
                observation, was_cached = self._execute_tool_cached(tool_name, tool_args, tool_cache)
                self._notify_progress(step_num, self.MAX_ITERATIONS, "分析结果中...")

                scratchpad.append(AgentStep(
                    step_num=step_num,
                    thought=parsed.get("thought", ""),
                    action=f"{tool_name}({json.dumps(tool_args, ensure_ascii=False)})",
                    observation=observation,
                    cached=was_cached
                ))
                self._notify_step(scratchpad[-1])

            # Handle: Pipeline (3.3)
            elif parsed["type"] == "pipeline":
                pipeline_steps = parsed["pipeline_steps"]
                observations = []
                for ps in pipeline_steps:
                    t_name, t_args = ps["tool_name"], ps["tool_args"]
                    tools_used.append(t_name)
                    obs, was_cached = self._execute_tool_cached(t_name, t_args, tool_cache)
                    observations.append(f"[{t_name}]: {obs}")

                combined_obs = "\n---\n".join(observations)
                action_display = " → ".join(ps["tool_name"] for ps in pipeline_steps)
                self._notify_progress(step_num, self.MAX_ITERATIONS, f"Pipeline: {action_display}")

                scratchpad.append(AgentStep(
                    step_num=step_num,
                    thought=parsed.get("thought", ""),
                    action=f"pipeline({action_display})",
                    observation=combined_obs
                ))
                self._notify_step(scratchpad[-1])

            else:
                # Still unknown after retry
                scratchpad.append(AgentStep(
                    step_num=step_num,
                    thought=f"[解析异常] {response[:200]}",
                ))
                if step_num >= 2 and all(s.action is None for s in scratchpad[-2:]):
                    logger.error("[AGENT] 连续解析失败，终止推理")
                    return AgentResult(
                        answer=response,
                        scratchpad=scratchpad, tools_used=tools_used,
                        iterations=step_num
                    )

        # Max iterations reached
        logger.warning(f"[AGENT] 达到最大迭代次数 {self.MAX_ITERATIONS}")
        self._notify_progress(self.MAX_ITERATIONS, self.MAX_ITERATIONS, "正在生成最终回答...")
        final_answer = self._force_final_answer(user_goal, params_str, scratchpad)
        return AgentResult(
            answer=final_answer,
            scratchpad=scratchpad, tools_used=tools_used,
            iterations=self.MAX_ITERATIONS
        )

    def _generate_plan(self, user_goal: str, params_str: str) -> str:
        """Generate execution plan before ReAct loop. Returns plan text or empty string."""
        # Skip planning for simple questions (short goals without design keywords)
        design_keywords = ["设计", "推荐", "参数", "优化", "对比", "分析", "生成", "验证"]
        if len(user_goal) < 15 and not any(kw in user_goal for kw in design_keywords):
            return ""

        try:
            self._notify_progress(0, self.MAX_ITERATIONS, "制定执行计划...")
            prompt = PLANNING_PROMPT.format(user_goal=user_goal)
            messages = [
                {"role": "system", "content": "你是 CIC 滤波器设计助手。请为用户目标制定简洁的执行计划。"},
                {"role": "user", "content": prompt}
            ]
            if params_str:
                messages[0]["content"] += f"\n\n当前设计参数:\n```json\n{params_str}\n```"

            plan = self.llm._call_api_with_messages(messages, temperature=0.1, max_tokens=512)
            return plan.strip()
        except RuntimeError:
            logger.warning("[AGENT] 规划阶段失败，跳过")
            return ""

    def _build_messages(self, user_goal: str, params_str: str,
                        scratchpad: list[AgentStep], plan_text: str = "") -> list[dict]:
        system_content = REACT_SYSTEM_PROMPT.format(tools_description=self._tools_description)

        if params_str:
            system_content += f"\n\n## 用户当前设计参数\n```json\n{params_str}\n```"

        messages = [{"role": "system", "content": system_content}]

        # Inject plan if available
        user_content = f"用户目标: {user_goal}"
        if plan_text:
            user_content += f"\n\n## 执行计划\n{plan_text}\n\n请按计划逐步执行。"
        messages.append({"role": "user", "content": user_content})

        if scratchpad:
            history_text = self._format_scratchpad_for_llm(scratchpad)
            messages.append({"role": "assistant", "content": history_text})
            last_step = scratchpad[-1]
            if last_step.observation:
                messages.append({"role": "user", "content": f"Observation: {last_step.observation}"})

        return messages

    def _format_scratchpad_for_llm(self, scratchpad: list[AgentStep]) -> str:
        parts = []
        for step in scratchpad:
            parts.append(f"Thought: {step.thought}")
            if step.action:
                parts.append(f"Action: {step.action}")
        return "\n".join(parts)

    def _build_tools_description(self, tools: list[dict]) -> str:
        lines = []
        for tool in tools:
            name = tool["name"]
            desc = tool["description"]
            params = tool.get("parameters", {})
            lines.append(f"### {name}")
            lines.append(f"功能: {desc}")
            props = params.get("properties", {})
            required = params.get("required", [])
            if props:
                lines.append("参数:")
                for pname, pinfo in props.items():
                    req_mark = " (必需)" if pname in required else " (可选)"
                    pdesc = pinfo.get("description", "")
                    ptype = pinfo.get("type", "any")
                    lines.append(f"  - {pname} ({ptype}): {pdesc}{req_mark}")
            lines.append("")
        return "\n".join(lines)

    def _extract_balanced_json(self, text: str, start: int) -> Optional[str]:
        """Extract a balanced JSON object from text starting at position of first '{'."""
        idx = text.find('{', start)
        if idx == -1:
            return None
        depth = 0
        in_string = False
        escape_next = False
        for i in range(idx, len(text)):
            ch = text[i]
            if escape_next:
                escape_next = False
                continue
            if ch == '\\' and in_string:
                escape_next = True
                continue
            if ch == '"' and not escape_next:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return text[idx:i + 1]
        return None

    def _parse_response(self, text: str) -> dict:
        """
        Parse LLM output: Thought / Action / Pipeline / Final Answer / Clarification.
        Uses bracket-counting for nested JSON (1.2).
        Supports pipeline format (3.3) and clarification (2.3) and confidence (3.4).
        """
        # Extract Thought
        thought = ""
        thought_match = re.search(
            r"Thought:\s*(.*?)(?=\nAction:|\nFinal Answer:|\nClarification:|\nConfidence:|\Z)",
            text, re.DOTALL
        )
        if thought_match:
            thought = thought_match.group(1).strip()

        # Extract Confidence (3.4)
        confidence = ""
        conf_match = re.search(r"Confidence:\s*(high|medium|low)", text, re.IGNORECASE)
        if conf_match:
            confidence = conf_match.group(1).lower()

        # Check Clarification (2.3)
        clar_match = re.search(r"Clarification:\s*(.*?)(?=\n(?:Thought|Action|Final Answer):|\Z)", text, re.DOTALL)
        if clar_match and "Final Answer:" not in text:
            return {
                "type": "clarification",
                "thought": thought,
                "content": clar_match.group(1).strip()
            }

        # Check Final Answer
        final_match = re.search(r"Final Answer:\s*(.*)", text, re.DOTALL)
        if final_match:
            return {
                "type": "final_answer",
                "thought": thought,
                "content": final_match.group(1).strip(),
                "confidence": confidence
            }

        # Check Pipeline (3.3): Action: pipeline([tool_a({...}), tool_b({...})])
        pipeline_match = re.search(r"Action:\s*pipeline\s*\(\s*\[", text)
        if pipeline_match:
            pipeline_steps = self._parse_pipeline(text, pipeline_match.start())
            if pipeline_steps:
                return {
                    "type": "pipeline",
                    "thought": thought,
                    "pipeline_steps": pipeline_steps
                }

        # Check single Action with bracket-counting (1.2)
        action_match = re.search(r"Action:\s*(\w+)\s*\(", text)
        if action_match:
            tool_name = action_match.group(1)
            json_str = self._extract_balanced_json(text, action_match.end() - 1)
            if json_str:
                try:
                    tool_args = json.loads(json_str)
                except json.JSONDecodeError:
                    # Try repairing truncated/malformed JSON before giving up
                    from llm_helper import _repair_json
                    repaired = _repair_json(json_str)
                    if repaired is not None:
                        tool_args = repaired
                    else:
                        # Try fixing single quotes
                        try:
                            tool_args = json.loads(json_str.replace("'", '"'))
                        except json.JSONDecodeError:
                            return {"type": "unknown", "thought": thought}

                return {
                    "type": "tool_call",
                    "thought": thought,
                    "tool_name": tool_name,
                    "tool_args": tool_args
                }

        # Fallback: treat long non-formatted text as final answer
        if len(text.strip()) > 20 and "Thought:" not in text:
            return {
                "type": "final_answer",
                "thought": "",
                "content": text.strip(),
                "confidence": confidence
            }

        return {"type": "unknown", "thought": thought}

    def _parse_pipeline(self, text: str, start: int) -> Optional[list[dict]]:
        """Parse pipeline([tool_a({...}), tool_b({...})]) format."""
        steps = []
        pos = start
        while True:
            # Find next tool_name( pattern
            tool_match = re.search(r'(\w+)\s*\(', text[pos:])
            if not tool_match or tool_match.group(1) == 'pipeline':
                pos += tool_match.end() if tool_match else 1
                # Skip past 'pipeline(['
                continue
            actual_pos = pos + tool_match.start()
            tool_name = tool_match.group(1)
            if tool_name not in self.tools:
                # Might be 'pipeline' itself, skip
                pos = pos + tool_match.end()
                continue
            json_str = self._extract_balanced_json(text, pos + tool_match.end() - 1)
            if not json_str:
                break
            try:
                tool_args = json.loads(json_str)
            except json.JSONDecodeError:
                break
            steps.append({"tool_name": tool_name, "tool_args": tool_args})
            # Move past this tool call
            json_end = text.find(json_str, pos + tool_match.end() - 1) + len(json_str)
            pos = json_end
            # Check if there are more tools (look for comma or closing bracket)
            remaining = text[pos:pos + 20].strip()
            if remaining.startswith(')'):
                pos += 1
                remaining = text[pos:pos + 20].strip()
            if remaining.startswith(']'):
                break
            if remaining.startswith(','):
                pos += text[pos:].index(',') + 1
                continue
            break
        return steps if len(steps) >= 2 else None

    def _execute_tool_cached(self, name: str, args: dict,
                             cache: dict[str, str]) -> tuple[str, bool]:
        """Execute tool with per-run cache. Returns (result_json, was_cached)."""
        # Build cache key from tool name and sorted args
        try:
            cache_key = f"{name}:{json.dumps(args, sort_keys=True)}"
        except (TypeError, ValueError):
            cache_key = None

        if cache_key and cache_key in cache:
            logger.info(f"[TOOL] 缓存命中: {name}")
            return cache[cache_key], True

        result = self._execute_tool(name, args)

        if cache_key:
            cache[cache_key] = result

        return result, False

    def _execute_tool(self, name: str, args: dict) -> str:
        """Execute tool function with timeout protection."""
        logger.info(f"[TOOL] 开始执行工具: {name}, 参数: {args}")
        start_time = time.time()

        if name not in self.tools:
            logger.error(f"[TOOL] 工具不存在: {name}")
            return json.dumps(
                {"error": f"工具 '{name}' 不存在。可用工具: {list(self.tools.keys())}"},
                ensure_ascii=False
            )

        tool_info = self.tools[name]
        func = tool_info["function"]

        try:
            TOOL_TIMEOUT = 30 if name == "simulate_freq_response" else 10

            def _run_tool():
                if name in ("check_param_constraints", "generate_testbench"):
                    if "params" in args:
                        return func(args["params"])
                    else:
                        return func(args)
                else:
                    return func(**args)

            result = run_with_timeout(_run_tool, timeout_seconds=TOOL_TIMEOUT)
            elapsed = time.time() - start_time

            if isinstance(result, dict) and "error" in result:
                logger.warning(f"[TOOL] 工具返回错误: {result['error']}")
            else:
                logger.info(f"[TOOL] 工具执行完成，耗时: {elapsed:.4f}s")
            return json.dumps(result, ensure_ascii=False, indent=2)

        except TimeoutError as e:
            logger.error(f"[TOOL] 工具执行超时: {e}")
            return json.dumps({"error": f"工具执行超时: {e}"}, ensure_ascii=False)
        except TypeError as e:
            logger.error(f"[TOOL] 参数错误: {e}")
            return json.dumps({"error": f"参数错误: {e}"}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[TOOL] 工具执行异常: {type(e).__name__}: {e}")
            return json.dumps({"error": f"工具执行异常: {type(e).__name__}: {e}"}, ensure_ascii=False)

    def _force_final_answer(self, user_goal: str, params_str: str,
                            scratchpad: list[AgentStep]) -> str:
        messages = self._build_messages(user_goal, params_str, scratchpad)
        messages.append({
            "role": "user",
            "content": "推理步数已达上限。请根据以上所有工具调用的结果，直接给出你的 Final Answer。"
        })

        try:
            response = self.llm._call_api_with_messages(messages)
            final_match = re.search(r"Final Answer:\s*(.*)", response, re.DOTALL)
            if final_match:
                return final_match.group(1).strip()
            return response.strip()
        except RuntimeError:
            parts = ["(Agent 推理步数已达上限，以下是已收集的信息)"]
            for step in scratchpad:
                if step.observation:
                    parts.append(f"• {step.thought}: {step.observation[:150]}")
            return "\n".join(parts)
