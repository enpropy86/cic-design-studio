# llm_helper.py
# LLM辅助设计模块 (LLM-Assisted Design Module)
# 用于CIC滤波器参数建议、设计优化和智能对话

"""
LLM辅助设计模块 (升级版)

功能清单:
1. 参数建议 — 根据自然语言描述推荐CIC/FIR参数
2. 设计分析 — 定量分析当前参数的问题和改进方向
3. 参数解释 — 教学模式，解释参数的工程意义
4. 设计对比 — 对比两组参数的优劣
5. 自由对话 — 多轮对话，自动注入当前参数上下文

配置说明:
1. 填入你的 API_KEY
2. 根据服务商修改 API_URL 和 MODEL
3. 支持 OpenAI 兼容的 API 格式
"""

import json
import re
import os
import time
import logging
from typing import Optional
from datetime import datetime

# ==============================================================================
# 日志配置 (Logging Configuration)
# ==============================================================================

logger = logging.getLogger(__name__)

def _setup_logging() -> None:
    """延迟初始化日志配置，仅在首次实例化 LLMHelper 时调用"""
    if logger.handlers:
        return  # 已配置，跳过
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()  # 同时输出到控制台
        ]
    )
    logger.info(f"日志文件: {log_file}")

# ==============================================================================
# 用户配置区 (User Configuration)
# ==============================================================================

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")  # read from environment; set DEEPSEEK_API_KEY before running
API_URL = os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions")  # DeepSeek API endpoint
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

# ==============================================================================
# 网络连接测试
# ==============================================================================

def test_api_connection() -> dict:
    """
    测试 API 服务器连接（发送一个最小化的 API 请求来验证连接和密钥）

    Returns:
        dict: {
            "success": bool,
            "message": str,
            "elapsed": float
        }
    """
    logger.info(f"[NETWORK] 开始测试 API 连接: {API_URL}")
    start_time = time.time()

    try:
        import requests
        # 使用真实的 POST 请求进行测试（带 Authorization），
        # DeepSeek 不支持无认证的 HEAD 请求
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        test_data = {
            "model": MODEL,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1  # 最小化 token 消耗
        }
        resp = requests.post(
            API_URL,
            headers=headers,
            json=test_data,
            timeout=15
        )

        elapsed = time.time() - start_time

        if resp.status_code == 401:
            logger.error("[NETWORK] API Key 无效或已过期 (401 Unauthorized)")
            return {
                "success": False,
                "message": "API Key 无效或已过期，请检查 API_KEY 配置",
                "elapsed": elapsed
            }

        resp.raise_for_status()

        logger.info(f"[NETWORK] API 连接成功，耗时: {elapsed:.2f}s")
        return {
            "success": True,
            "message": f"连接成功，耗时: {elapsed:.2f}s",
            "elapsed": elapsed
        }

    except requests.exceptions.Timeout:
        elapsed = time.time() - start_time
        logger.error("[NETWORK] 连接超时 (15秒)")
        return {
            "success": False,
            "message": "连接超时 (15秒)",
            "elapsed": elapsed
        }

    except requests.exceptions.ConnectionError as e:
        elapsed = time.time() - start_time
        logger.error(f"[NETWORK] 无法连接到服务器: {e}")
        return {
            "success": False,
            "message": f"无法连接到服务器: {e}",
            "elapsed": elapsed
        }

    except requests.exceptions.HTTPError as e:
        elapsed = time.time() - start_time
        status_code = e.response.status_code if e.response else 'N/A'
        logger.error(f"[NETWORK] HTTP 错误 {status_code}: {e}")
        return {
            "success": False,
            "message": f"HTTP 错误 {status_code}: {e}",
            "elapsed": elapsed
        }

    except requests.exceptions.RequestException as e:
        elapsed = time.time() - start_time
        logger.error(f"[NETWORK] 请求错误: {type(e).__name__}: {e}")
        return {
            "success": False,
            "message": f"请求错误: {type(e).__name__}: {e}",
            "elapsed": elapsed
        }

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[NETWORK] 未知错误: {type(e).__name__}: {e}")
        return {
            "success": False,
            "message": f"未知错误: {type(e).__name__}: {e}",
            "elapsed": elapsed
        }

# ==============================================================================
# 系统提示词 (System Prompts) — 升级版
# ==============================================================================

SYSTEM_PROMPT_PARAMS = """你是一个资深的CIC (Cascaded Integrator-Comb) 滤波器设计专家，拥有15年FPGA数字信号处理经验。

## 核心知识

### CIC 位宽增长公式
内部寄存器位宽 = data_width + N * ceil(log2(R * M))
其中: N=级数, R=抽取/插值比, M=微分延迟

### 典型应用参数参考
| 应用场景 | 输入采样率 | 输出采样率 | 推荐 R | 推荐 N | 推荐 M |
|---------|-----------|-----------|--------|--------|--------|
| 语音通信 | 48kHz | 8kHz | 6 | 3-4 | 1 |
| 音频DAC | 44.1kHz→高 | 44.1kHz | 64-256 | 3-5 | 1 |
| 无线通信 (GSM) | 13MHz | 270.8kHz | 48 | 4 | 1 |

### FIR 补偿结构权衡
- 并联结构 (parallel): 最高吞吐量，使用较多DSP资源，每个时钟产出一个数据。
- 串联结构 (serial): 最低资源占用，只用一个DSP，但需要花费与抽头数相同数目的时钟周期处理一个数据，适合低采样率。
- 分布式算术 (da): LUT实现，无乘法器，适合DSP资源匮乏的FPGA。按位处理，需要数据位宽数目的时钟周期。

### 工具支持的参数约束
- R (抽取/插值比): 2 ~ 8192 (整数)
- N (CIC级数): 1 ~ 8 (整数)
- M (微分延迟): 1 ~ 4 (整数，通常取1或2)
- FIR抽头数: 必须为奇数 (对称FIR)
- FIR通带占比: 0.1 ~ 0.9

### 图像展示场景的经验规则
- 当用户明确提到 PNG、图像放大、像素、行列两遍、可分离 2D 插值、展示效果等关键词时，优先把它视为**视觉展示场景**，而不是极限频谱指标优化场景。
- 这类场景默认优先推荐 `Interpolator_FIR`。
- 若用户没有强制极低纹波/极高阻带指标，优先选择轻量可演示参数：`stages=3`, `delay=1`, `fir_taps=15~31`, `fir_type=parallel`。
- 对于 4× 图像放大，`passband_ratio` 优先考虑 0.25~0.35，避免把通带设得过宽导致补偿困难。
- 若用户同时给出非常苛刻的纹波/阻带指标，但又强调"展示结果"、"视觉效果即可"、"资源不用太大"，则优先满足可生成、可仿真、视觉上平滑，允许在 reasoning / warnings 中说明该参数不是极限频响最优。

## 输出要求

用户会描述采样率转换需求，请综合推荐架构模式、过滤参数组合、和FIR补偿滤波器结构。

**只返回JSON，不要任何其他文字。** JSON结构如下：
{
    "mode": "<架构模式: Decimator | Interpolator | Decimator_FIR | Interpolator_FIR>",
    "fir_type": "<FIR结构选择: parallel | serial | da>",
    "ratio": <抽取/插值比 R, 整数>,
    "stages": <CIC级数 N, 1-8之间>,
    "delay": <微分延迟 M, 通常1或2>,
    "fir_taps": <FIR补偿滤波器阶数, 奇数, 推荐15-31>,
    "passband_ratio": <通带比例, 0.1-0.9>,
    "reasoning": "<详细的设计理由，包括为什么这样选择 mode 和 fir_type 以及各参数>",
    "warnings": ["<可能的风险或注意事项，数组>"],
    "bit_growth": <位宽增长量, 整数>,
    "alternatives": {
        "balanced": {"mode": "<模式>", "fir_type": "<fir类型>", "ratio": <R>, "stages": <N>, "delay": <M>, "fir_taps": <阶数>, "note": "<权衡说明>"},
        "low_resource": {"mode": "<模式>", "fir_type": "<fir类型>", "ratio": <R>, "stages": <N>, "delay": <M>, "fir_taps": <阶数>, "note": "<权衡说明>"},
        "high_performance": {"mode": "<模式>", "fir_type": "<fir类型>", "ratio": <R>, "stages": <N>, "delay": <M>, "fir_taps": <阶数>, "note": "<权衡说明>"}
    }
}"""

SYSTEM_PROMPT_ANALYZE = """你是一个资深CIC滤波器设计专家，请对给定的设计参数进行定量分析。

## 分析维度与公式

### 1. 位宽增长分析
- 公式: growth_bits = N * ceil(log2(R * M))
- 内部寄存器宽度: data_width + growth_bits
- 判断标准: ≤20bits(优), ≤30bits(良), ≤40bits(可), >40bits(差)

### 2. 通带衰减 (Passband Droop)
- 近似公式: droop ≈ -N * 0.36 * (f/f_pass)^2 dB (f_pass = fs_out / 2)
- 在通带边缘的衰减量是关键指标
- FIR补偿后残余droop应 < 0.1dB

### 3. 阻带抑制
- N级CIC在 fs_out/2 处的抑制约为: N * 13 dB
- 对于语音: >60dB, 通信: >70dB, 仪器: >80dB

### 4. FPGA 资源估算
- CIC LUTs ≈ (data_width + growth_bits) * N * 1.5
- CIC FFs ≈ (data_width + growth_bits) * N * 2
- FIR DSPs = ceil(taps / 2) (利用对称性)
- FIR FFs ≈ taps * data_width + 50

### 5. 延迟分析
- CIC延迟: N * M 个采样周期 (输入时钟)
- FIR延迟: (taps - 1) / 2 个采样周期 (输出时钟)

## 输出格式

请用中文回答，结构化输出（使用Markdown格式）：

### 🏆 综合评分: X/10

### 📊 各维度评分
| 维度 | 评分 | 数值 | 说明 |
|------|-----|------|------|
| 位宽增长 | X/10 | Xbits | ... |
| 通带平坦度 | X/10 | XdB | ... |
| 阻带抑制 | X/10 | XdB | ... |
| 资源占用 | X/10 | X LUTs | ... |

### ⚠️ 关键问题
(列出最需要关注的问题)

### 💡 改进建议
(给出具体的参数调整建议)"""

SYSTEM_PROMPT_EXPLAIN = """你是一个耐心的数字信号处理教师，擅长用通俗易懂的语言解释CIC滤波器的工程概念。

## 你的任务
用户会给你一组CIC滤波器参数，请解释每个参数在工程上的意义和设计权衡。

## 解释要求
1. 每个参数单独段落，使用类比帮助理解
2. 解释参数之间的相互影响
3. 给出该参数在当前取值下的具体效果
4. 使用 emoji 增加可读性

## 关键知识点
- CIC = 级联积分梳状滤波器，由积分器和梳状器级联而成
- 位宽增长 = N * ceil(log2(R*M))，这是CIC的"代价"
- 抽取(Decimator): 先CIC抽取，再FIR补偿 → 降采样
- 插值(Interpolator): 先FIR预补偿，再CIC插值 → 升采样
- FIR补偿的目的是修正CIC的通带衰减(droop)

请用中文回答，语气友好，像在给同事讲解。"""

SYSTEM_PROMPT_COMPARE = """你是一个CIC滤波器设计专家，请对比分析两组设计参数的优劣。

## 对比维度
1. 位宽增长: growth = N * ceil(log2(R*M))
2. 阻带抑制: ≈ N * 13dB
3. 资源占用: LUTs, FFs, DSPs
4. 通带平坦度
5. 适用场景

## 输出格式（中文，Markdown）
使用表格对比，最后给出推荐方案和理由。"""

SYSTEM_PROMPT_CHAT = """你是CIC滤波器设计工具的AI助手，擅长CIC/FIR滤波器设计、FPGA实现和数字信号处理。

## 工具信息
用户正在使用一个CIC滤波器RTL代码生成器，功能包括：
- CIC抽取器/插值器代码生成 (Verilog)
- FIR补偿滤波器自动设计
- 频率响应预览
- 支持 Xilinx/Altera 复位风格
- 支持多种截断模式 (直接截断/四舍五入/饱和截断/全精度)

## 关键公式
- CIC位宽增长: N * ceil(log2(R*M))
- 阻带抑制: ≈ N * 13dB @fs/(2R)
- FIR对称结构DSP用量: ceil(taps/2)

## 注意事项
- 你**不负责直接编写Verilog代码**，代码由工具自动生成
- 你的职责是帮助用户理解参数选择、设计权衡和优化方向
- 回答简洁、条理清晰，使用中文
- 当用户要求推荐、配置、生成或应用参数时，回复末尾必须追加一个独立的 ```json 代码块，代码块中只放可被UI一键应用的参数对象。
- 一键应用 JSON 的键名固定为: `mode, ratio, stages, delay, fir_taps, passband_ratio, fir_type, data_width, fs_in`。
- 如果用户提到 PNG、图像、灰度图、4x 放大、行列两遍、可分离 2D 插值等图像展示场景，`mode` 必须使用 `Interpolator_FIR`，不要使用纯 `Interpolator`。
- 图像 4x 展示场景优先使用轻量参数: `ratio=4`, `stages=3`, `delay=1`, `fir_taps=15~31`, `passband_ratio=0.25~0.35`, `fir_type=parallel`, `data_width=8`, `fs_in=10000000`。

当前用户的设计参数会附在对话中，请基于这些参数进行回答。"""

# ==============================================================================
# 聊天历史管理 (Chat History Manager)
# ==============================================================================

HISTORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".chat_history")

def _repair_json(text: str) -> Optional[dict]:
    """Salvage a (possibly truncated or fenced) JSON object from LLM output.

    Strategies tried in order:
      1. strip markdown fences, parse the first balanced {...} block
      2. progressively close unclosed braces
      3. replace single quotes with double quotes
      4. drop a dangling trailing string (truncated mid-value)
    Returns None if nothing parses as a dict.
    """
    if not text or not text.strip():
        return None
    t = re.sub(r"^```(?:json)?\s*", "", text.strip())
    t = re.sub(r"\s*```$", "", t)
    start = t.find("{")
    if start == -1:
        return None
    obj = t[start:]

    def _try(s):
        if not s:
            return None
        try:
            v = json.loads(s)
            return v if isinstance(v, dict) else None
        except json.JSONDecodeError:
            try:
                v = json.loads(s.replace("'", '"'))
                return v if isinstance(v, dict) else None
            except json.JSONDecodeError:
                return None

    # 1) balanced block as-is
    v = _try(obj)
    if v is not None:
        return v

    # 2) progressively close braces (allow a dangling last value)
    for close in range(1, 8):
        v = _try(obj + "}" * close)
        if v is not None:
            return v

    # 3) truncate to each brace/string boundary, then close
    for cut in range(len(obj), 0, -1):
        prefix = obj[:cut]
        if prefix.endswith((",", ":", "{", "}")):
            continue
        for close in range(0, 5):
            v = _try(prefix + "}" * close)
            if v is not None:
                return v
        # also try cutting an unterminated string: drop trailing quote-less token
        m = re.match(r"\{[\s\S]*", prefix)
        if m:
            fixed = re.sub(r'"\s*[^",}]*$', '"', prefix)
            v = _try(fixed + "}" * 3)
            if v is not None:
                return v
    return None

def _ensure_history_dir() -> str:
    """确保历史记录目录存在"""
    os.makedirs(HISTORY_DIR, exist_ok=True)
    return HISTORY_DIR


# ==============================================================================
# LLM助手类 (LLM Helper Class) — 升级版
# ==============================================================================

class LLMHelper:
    """
    LLM辅助设计类 (升级版)
    提供参数建议、设计分析、参数解释、设计对比和多轮对话功能
    """
    
    def __init__(self, api_key: Optional[str] = None,
                 api_url: Optional[str] = None,
                 model: Optional[str] = None):
        """
        初始化LLM助手

        Args:
            api_key: API密钥，如果不传则使用模块级配置
            api_url: API地址
            model: 模型名称
        """
        _setup_logging()
        self.api_key = api_key or API_KEY
        self.api_url = api_url or API_URL
        self.model = model or MODEL
        self.chat_history: list[dict] = []  # 多轮对话历史
        self._token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        # 初始化时进行网络连接测试
        if self.is_configured():
            logger.info(f"[NETWORK] API URL: {self.api_url}")
            logger.info(f"[NETWORK] 模型: {self.model}")
            conn_result = test_api_connection()
            if conn_result["success"]:
                logger.info(f"[NETWORK] 网络连接正常: {conn_result['message']}")
            else:
                logger.warning(f"[NETWORK] 网络连接异常: {conn_result['message']}")
                logger.warning("[NETWORK] Agent 可能无法正常工作，请检查网络连接")
        else:
            logger.warning("[NETWORK] API Key 未配置，跳过网络测试")

    def is_configured(self) -> bool:
        """检查是否已配置API Key"""
        return self.api_key != "YOUR_API_KEY_HERE" and len(self.api_key) > 10
    
    # ------------------------------------------------------------------
    # 核心功能方法
    # ------------------------------------------------------------------
    
    def _call_with_prompt(self, system_prompt, user_prompt, max_tokens=None):
        if not self.is_configured():
            raise ValueError("请先在 llm_helper.py 中配置 API_KEY")
        return self._call_api(
            system_prompt=system_prompt, user_prompt=user_prompt,
            max_tokens=max_tokens
        )

    def suggest_params(self, description: str, max_retries: int = 3) -> dict:
        last_err: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                response = self._call_with_prompt(
                    SYSTEM_PROMPT_PARAMS,
                    f"用户需求: {description}",
                    max_tokens=2048
                )
            except RuntimeError as e:
                last_err = e
                continue
            parsed = _repair_json(response)
            if parsed is not None and isinstance(parsed, dict):
                return parsed
            last_err = RuntimeError(f"无法解析LLM响应为JSON，尝试 {attempt + 1}/{max_retries} 次仍失败。原始响应: {response[:300]}")
        raise last_err if last_err is not None else RuntimeError("suggest_params failed")

    def analyze_design(self, params: dict) -> str:
        params_str = json.dumps(params, indent=2, ensure_ascii=False)
        return self._call_with_prompt(
            SYSTEM_PROMPT_ANALYZE,
            f"请分析以下CIC滤波器设计:\n\n{params_str}",
            max_tokens=4096
        )

    def explain_params(self, params: dict) -> str:
        params_str = json.dumps(params, indent=2, ensure_ascii=False)
        return self._call_with_prompt(
            SYSTEM_PROMPT_EXPLAIN,
            f"请解释以下CIC滤波器参数的工程意义:\n\n{params_str}"
        )

    def compare_designs(self, params_a: dict, params_b: dict) -> str:
        prompt = (
            "请对比以下两组CIC滤波器设计:\n\n"
            f"## 方案A\n{json.dumps(params_a, indent=2, ensure_ascii=False)}\n\n"
            f"## 方案B\n{json.dumps(params_b, indent=2, ensure_ascii=False)}"
        )
        return self._call_with_prompt(SYSTEM_PROMPT_COMPARE, prompt)
    
    def chat(self, user_message: str, context_params: Optional[dict] = None) -> str:
        """
        多轮对话 — 支持追问和上下文记忆
        
        Args:
            user_message: 用户消息
            context_params: 当前设计参数 (自动注入上下文)
            
        Returns:
            str: AI回复
        """
        if not self.is_configured():
            raise ValueError("请先在 llm_helper.py 中配置 API_KEY")
        
        # 构建系统消息 (含当前参数上下文)
        system_content = SYSTEM_PROMPT_CHAT
        if context_params:
            params_str = json.dumps(context_params, indent=2, ensure_ascii=False)
            system_content += f"\n\n## 用户当前设计参数\n```json\n{params_str}\n```"
        
        # 添加用户消息到历史
        self.chat_history.append({"role": "user", "content": user_message})
        
        # 构建消息列表 (系统 + 历史)
        messages = [{"role": "system", "content": system_content}]
        # 保留最近10轮对话，避免超出token限制
        recent_history = self.chat_history[-20:]
        messages.extend(recent_history)
        
        # 调用API
        reply = self._call_api_with_messages(messages)
        
        # 保存AI回复到历史
        self.chat_history.append({"role": "assistant", "content": reply})
        if len(self.chat_history) > 200:
            self.chat_history = self.chat_history[-100:]

        return reply
    
    def clear_history(self) -> None:
        """清空对话历史"""
        self.chat_history.clear()

    def get_usage(self) -> dict:
        """获取累计 token 用量"""
        return dict(self._token_usage)

    def reset_usage(self) -> None:
        """重置 token 用量计数"""
        self._token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    
    # ------------------------------------------------------------------
    # 对话历史持久化
    # ------------------------------------------------------------------
    
    def save_history(self, session_name: Optional[str] = None) -> str:
        """
        保存对话历史到本地文件
        
        Args:
            session_name: 会话名称，不传则用时间戳
            
        Returns:
            str: 保存的文件路径
        """
        _ensure_history_dir()
        if not session_name:
            session_name = time.strftime("%Y%m%d_%H%M%S")
        
        filepath = os.path.join(HISTORY_DIR, f"{session_name}.json")
        data = {
            "session_name": session_name,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "messages": self.chat_history
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        return filepath
    
    def load_history(self, session_name: str) -> bool:
        """
        加载历史对话记录
        
        Args:
            session_name: 会话名称
            
        Returns:
            bool: 是否加载成功
        """
        filepath = os.path.join(HISTORY_DIR, f"{session_name}.json")
        if not os.path.exists(filepath):
            return False
        
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        self.chat_history = data.get("messages", [])
        return True
    
    def list_sessions(self) -> list[dict]:
        """
        列出所有保存的对话会话
        
        Returns:
            list: 会话信息列表 [{"name": ..., "timestamp": ..., "count": ...}]
        """
        _ensure_history_dir()
        sessions = []
        for filename in os.listdir(HISTORY_DIR):
            if not filename.endswith('.json'):
                continue
            filepath = os.path.join(HISTORY_DIR, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                sessions.append({
                    "name": data.get("session_name", filename[:-5]),
                    "timestamp": data.get("timestamp", ""),
                    "count": len(data.get("messages", []))
                })
            except (json.JSONDecodeError, OSError):
                continue
        
        sessions.sort(key=lambda s: s["timestamp"], reverse=True)
        return sessions
    
    # ------------------------------------------------------------------
    # API 调用层
    # ------------------------------------------------------------------
    
    def _call_api(self, system_prompt: str, user_prompt: str,
                  temperature: Optional[float] = None,
                  max_tokens: Optional[int] = None) -> str:
        """
        调用LLM API (单轮)

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            temperature: 采样温度
            max_tokens: 最大输出 token 数

        Returns:
            str: API响应内容
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        return self._call_api_with_messages(messages, temperature=temperature, max_tokens=max_tokens)
    
    def _call_api_with_messages(self, messages: list[dict],
                                temperature: Optional[float] = None,
                                max_tokens: Optional[int] = None) -> str:
        """
        调用LLM API (通用 — 支持多轮消息，带重试机制)

        Args:
            messages: 消息列表
            temperature: 采样温度 (默认 0.3)
            max_tokens: 最大输出 token 数 (默认 2048)

        Returns:
            str: API响应内容
        """
        try:
            import requests
        except ImportError:
            raise RuntimeError("需要安装 requests 库: pip install requests")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        data = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else 0.3,
            "max_tokens": max_tokens if max_tokens is not None else 2048
        }

        # 重试机制配置
        max_retries = 1
        base_timeout = 60  # 单次请求超时：60秒足够复杂推理

        for attempt in range(max_retries + 1):
            try:
                logger.info(f"[LLM_API] 开始调用 API，消息数: {len(messages)}，尝试 {attempt + 1}/{max_retries + 1}")
                start_time = time.time()

                resp = requests.post(
                    self.api_url,
                    headers=headers,
                    json=data,
                    timeout=(10, base_timeout)  # (connect_timeout, read_timeout)
                )
                resp.raise_for_status()

                result = resp.json()
                content = result["choices"][0]["message"]["content"]
                elapsed = time.time() - start_time

                # Token usage tracking
                usage = result.get("usage", {})
                if usage:
                    self._token_usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
                    self._token_usage["completion_tokens"] += usage.get("completion_tokens", 0)
                    self._token_usage["total_tokens"] += usage.get("total_tokens", 0)
                    logger.debug(f"[LLM_API] Token usage this call: {usage}")

                # 如果响应时间接近超时，记录警告
                if elapsed > base_timeout * 0.8:  # 超过80%的超时时间
                    logger.warning(f"[LLM_API] 响应较慢: {elapsed:.2f}s (超时: {base_timeout}s)")
                elif elapsed > base_timeout * 0.5:
                    logger.info(f"[LLM_API] 响应较慢: {elapsed:.2f}s，响应长度: {len(content)} 字符")
                else:
                    logger.info(f"[LLM_API] API 调用成功，耗时: {elapsed:.2f}s，响应长度: {len(content)} 字符")
                return content

            except requests.exceptions.Timeout:
                logger.warning(f"[LLM_API] API 请求超时 ({base_timeout}秒)")
                if attempt < max_retries:
                    wait_time = (attempt + 1) * 5
                    logger.info(f"[LLM_API] {wait_time}秒后重试...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"[LLM_API] 所有重试均超时")
                    raise RuntimeError(f"API请求超时 ({base_timeout * (max_retries + 1)}秒累计)，请检查网络连接")

            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code if e.response else 'N/A'
                if status_code == 401:
                    logger.error("[LLM_API] API Key 无效或已过期 (401)")
                    raise RuntimeError("API Key 无效或已过期，请检查 llm_helper.py 中的 API_KEY 配置")
                logger.error(f"[LLM_API] HTTP 错误 {status_code}: {e}")
                raise RuntimeError(f"HTTP 错误 {status_code}: {e}")

            except requests.exceptions.ConnectionError:
                logger.error("[LLM_API] 无法连接到API服务器，请检查网络")
                raise RuntimeError("无法连接到API服务器，请检查网络")

            except requests.exceptions.RequestException as e:
                logger.error(f"[LLM_API] API请求失败: {e}")
                raise RuntimeError(f"API请求失败: {e}")

            except (KeyError, IndexError) as e:
                logger.error(f"[LLM_API] API响应格式异常: {e}")
                raise RuntimeError(f"API响应格式异常: {e}")


# ==============================================================================
# 便捷函数 (Convenience Functions)
# ==============================================================================

def quick_suggest(description: str) -> dict:
    """快速获取参数建议"""
    helper = LLMHelper()
    return helper.suggest_params(description)


def quick_analyze(params: dict) -> str:
    """快速分析设计"""
    helper = LLMHelper()
    return helper.analyze_design(params)


def quick_explain(params: dict) -> str:
    """快速解释参数"""
    helper = LLMHelper()
    return helper.explain_params(params)


# ==============================================================================
# 测试代码 (Test Code)
# ==============================================================================

if __name__ == "__main__":
    helper = LLMHelper()
    
    if not helper.is_configured():
        print("=" * 50)
        print("LLM Helper 测试")
        print("=" * 50)
        print("\n⚠️  API Key 未配置")
        print("请编辑 llm_helper.py 文件，在 API_KEY 变量中填入你的 API Key")
        print("\n示例配置:")
        print('  API_KEY = "sk-xxxxxxxxxxxxxxxxxxxx"')
        print('  API_URL = "https://api.openai.com/v1/chat/completions"')
        print('  MODEL = "gpt-4"')
    else:
        print("API Key 已配置，可以使用 LLM 辅助功能")
        print(f"模型: {helper.model}")
        print(f"API: {helper.api_url}")
        
        # 测试参数建议
        try:
            print("\n测试参数建议...")
            params = helper.suggest_params("音频采样率从 48kHz 降到 8kHz")
            print(f"推荐参数: {json.dumps(params, indent=2, ensure_ascii=False)}")
        except Exception as e:
            print(f"测试失败: {e}")
