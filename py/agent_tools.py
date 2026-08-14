# agent_tools.py
# Agent 工具函数库 (Agent Tool Functions)
# 提供确定性计算工具，供 DesignAgent 在 ReAct 推理循环中调用

"""
Agent 工具注册表

每个工具是一个纯 Python 函数，接收关键字参数，返回 dict。
工具不调用 LLM，结果完全确定性，可复现。

工具清单:
1. calc_bit_growth       — CIC 位宽增长计算
2. simulate_freq_response — CIC+FIR 频率响应数值仿真
3. check_param_constraints — 参数合法性与约束检查
4. estimate_fpga_resource  — FPGA 资源占用估算
5. generate_matlab_script  — 生成 MATLAB 验证脚本
6. suggest_uvm_scenarios   — UVM 测试场景建议
7. suggest_design_params   — 自然语言需求 → 候选参数 (调用 LLM)
"""

import math
import json
import re
from typing import Any

from fir_calc import calc_cic_growth, get_useful_band_edge
import fir_calc

# ==============================================================================
# 工程约束常量 (Engineering Constraint Constants)
# ==============================================================================
# CIC 位宽增长严重等级阈值 (bits)
_BIT_GROWTH_EXCELLENT  = 16
_BIT_GROWTH_GOOD       = 24
_BIT_GROWTH_ACCEPTABLE = 32
_BIT_GROWTH_LARGE      = 40

# FPGA 资源等级阈值
_RESOURCE_LIGHT_DSPS = 8
_RESOURCE_LIGHT_LUTS = 1000
_RESOURCE_MED_DSPS   = 16
_RESOURCE_MED_LUTS   = 3000
_RESOURCE_HEAVY_DSPS = 32
_RESOURCE_HEAVY_LUTS = 6000

# ==============================================================================
# Tool 1: 位宽增长计算 (Bit Width Growth)
# ==============================================================================

def calc_bit_growth(R: int, N: int, M: int = 1, data_width: int = 16) -> dict:
    """
    计算 CIC 滤波器的位宽增长量

    公式: growth = N * ceil(log2(R * M))
    内部寄存器宽度: data_width + growth

    Args:
        R: 抽取/插值比 (2~8192)
        N: CIC 级数 (1~8)
        M: 微分延迟 (1~4, 默认1)
        data_width: 输入数据位宽 (4~64, 默认16)

    Returns:
        dict: {
            "bit_growth": int,
            "internal_width": int,
            "formula": str,
            "severity": str  — "优秀"/"良好"/"可接受"/"偏大"/"危险"
        }
    """
    growth = calc_cic_growth(N, M, R)
    internal = data_width + growth

    # 严重等级评估
    if growth <= _BIT_GROWTH_EXCELLENT:
        severity = "优秀"
    elif growth <= _BIT_GROWTH_GOOD:
        severity = "良好"
    elif growth <= _BIT_GROWTH_ACCEPTABLE:
        severity = "可接受"
    elif growth <= _BIT_GROWTH_LARGE:
        severity = "偏大"
    else:
        severity = "危险"

    ceil_val = math.ceil(math.log2(R * M))
    return {
        "bit_growth": growth,
        "internal_width": internal,
        "formula": f"N * ceil(log2(R*M)) = {N} * ceil(log2({R}*{M})) = {N} * {ceil_val} = {growth}",
        "severity": severity
    }


# ==============================================================================
# Tool 2: 频率响应仿真 (Frequency Response Simulation)
# ==============================================================================

def simulate_freq_response(R: int, N: int, M: int = 1,
                           taps: int = 21, passband_ratio: float = 0.5,
                           coeff_width: int = 16,
                           mode: str = 'Decimator_FIR') -> dict:
    """
    数值仿真 CIC+FIR 级联频率响应，返回关键性能指标

    内部调用 fir_calc.analyze_response_wide()

    Args:
        R: 抽取/插值比
        N: CIC 级数
        M: 微分延迟
        taps: FIR 补偿滤波器抽头数 (奇数)
        passband_ratio: FIR 通带占比 (0.1~0.9)
        coeff_width: FIR 系数位宽
        mode: 'Decimator_FIR' (默认) | 'Interpolator_FIR'

    Returns:
        dict: {
            "passband_droop_db": float,       — 有效带宽内最大衰减 (dB)
            "stopband_attenuation_db": float,  — 输出 Nyquist 处衰减 (dB)
            "passband_ripple_db": float,       — 有效带宽内纹波 (dB)
            "quality_grade": str,              — 综合评级
            "cic_only_droop_db": float         — 无补偿时有效带宽内衰减
        }
    """
    try:
        import numpy as np
        from fir_calc import analyze_response_wide
    except ImportError as e:
        return {"error": f"依赖缺失: {e}"}

    mode_l = (mode or 'Decimator_FIR').lower()
    if 'interpolator' in mode_l:
        mode = 'Interpolator_FIR'
    else:
        mode = 'Decimator_FIR'

    freqs, cic_db, fir_db, total_db = analyze_response_wide(
        N=N, R=R, M=M, taps=taps,
        passband_ratio=passband_ratio, coeff_width=coeff_width,
        mode=mode
    )

    pb_end_norm = get_useful_band_edge(mode, R)
    # passband metrics are measured inside the compensation band only; beyond
    # it the FIR intentionally rolls off (alias/image rejection)
    if passband_ratio is not None:
        pb_end_norm = min(1.0, pb_end_norm * max(0.1, min(0.99, float(passband_ratio))))
    pb_mask = freqs <= pb_end_norm

    if not np.any(pb_mask):
        return {"error": "有效带宽范围异常，无法分析"}

    total_pb = total_db[pb_mask]
    total_pb_valid = total_pb[np.isfinite(total_pb)]
    if len(total_pb_valid) == 0:
        return {"error": "频响数据异常"}

    passband_droop = float(np.min(total_pb_valid))
    passband_max = float(np.max(total_pb_valid))
    passband_ripple = passband_max - passband_droop

    cic_pb = cic_db[pb_mask]
    cic_pb_valid = cic_pb[np.isfinite(cic_pb)]
    cic_only_droop = float(np.min(cic_pb_valid)) if len(cic_pb_valid) > 0 else -99.0

    stopband_atten = float(total_db[-1]) if len(total_db) > 0 else -999.0

    if abs(passband_droop) < 0.1 and passband_ripple < 0.15:
        quality = "优秀"
    elif abs(passband_droop) < 0.5 and passband_ripple < 0.5:
        quality = "良好"
    elif abs(passband_droop) < 1.0:
        quality = "可接受"
    else:
        quality = "较差"

    return {
        "passband_droop_db": round(passband_droop, 3),
        "stopband_attenuation_db": round(stopband_atten, 3),
        "passband_ripple_db": round(passband_ripple, 3),
        "cic_only_droop_db": round(cic_only_droop, 3),
        "quality_grade": quality
    }


# ==============================================================================
# Tool 3: 参数约束检查 (Parameter Constraint Check)
# ==============================================================================

# 约束定义表
PARAM_CONSTRAINTS = {
    "ratio":          {"min": 2,   "max": 8192, "type": "int",   "label": "抽取/插值比 R"},
    "stages":         {"min": 1,   "max": 8,    "type": "int",   "label": "CIC级数 N"},
    "delay":          {"min": 1,   "max": 4,    "type": "int",   "label": "微分延迟 M"},
    "data_width":     {"min": 4,   "max": 64,   "type": "int",   "label": "数据位宽"},
    "fir_taps":       {"min": 3,   "max": 127,  "type": "odd",   "label": "FIR抽头数"},
    "passband_ratio": {"min": 0.1, "max": 0.9,  "type": "float", "label": "FIR通带占比"},
    "coeff_width":    {"min": 8,   "max": 32,   "type": "int",   "label": "FIR系数位宽"},
}


def check_param_constraints(params: dict) -> dict:
    """
    检查参数是否在合法范围内

    Args:
        params: 参数字典，支持的键见 PARAM_CONSTRAINTS

    Returns:
        dict: {
            "valid": bool,
            "violations": list[dict],   — 违规项
            "checked": int              — 检查的参数个数
        }
    """
    violations: list[dict] = []
    checked = 0

    for key, value in params.items():
        if key not in PARAM_CONSTRAINTS:
            continue
        checked += 1
        rule = PARAM_CONSTRAINTS[key]
        item = {"param": key, "label": rule["label"], "value": value}

        # 类型检查
        try:
            if rule["type"] == "int":
                val_num = int(value)
            elif rule["type"] == "odd":
                val_num = int(value)
            elif rule["type"] == "float":
                val_num = float(value)
            else:
                continue
        except (ValueError, TypeError):
            item["issue"] = f"无法转换为{rule['type']}类型"
            item["ok"] = False
            violations.append(item)
            continue

        # 范围检查
        if val_num < rule["min"] or val_num > rule["max"]:
            item["issue"] = f"值 {val_num} 超出范围 [{rule['min']}, {rule['max']}]"
            item["ok"] = False
            violations.append(item)
            continue

        # 奇数检查
        if rule["type"] == "odd" and val_num % 2 == 0:
            item["issue"] = f"FIR抽头数 {val_num} 必须为奇数"
            item["ok"] = False
            violations.append(item)
            continue

        item["ok"] = True

    # 参数间依赖关系检查
    warnings = []
    _r = params.get("ratio") or params.get("R")
    _n = params.get("stages") or params.get("N")
    _m = params.get("delay") or params.get("M", 1)
    _dw = params.get("data_width", 16)

    if _r is not None and _n is not None:
        try:
            _r, _n, _m, _dw = int(_r), int(_n), int(_m), int(_dw)
            bit_growth = calc_cic_growth(_n, _m, _r)
            internal_width = _dw + bit_growth
            if internal_width > 64:
                violations.append({
                    "param": "R+N+M+data_width", "label": "内部寄存器位宽",
                    "value": internal_width,
                    "issue": f"内部寄存器位宽 {internal_width} bits 超过64位，FPGA实现困难",
                    "ok": False
                })
            elif internal_width > 48:
                warnings.append(f"内部寄存器位宽 {internal_width} bits 偏大，建议减小 N 或 R")
        except (ValueError, TypeError):
            pass

    _pb = params.get("passband_ratio")
    _taps = params.get("fir_taps")
    if _pb is not None and _taps is not None:
        try:
            if float(_pb) > 0.8 and int(_taps) < 15:
                warnings.append(f"passband_ratio={_pb} 较大而 fir_taps={_taps} 较少，FIR补偿效果可能不足")
        except (ValueError, TypeError):
            pass

    return {
        "valid": len(violations) == 0,
        "violations": violations,
        "warnings": warnings,
        "checked": checked
    }


# ==============================================================================
# Tool 4: FPGA 资源估算 (FPGA Resource Estimation)
# ==============================================================================

def estimate_fpga_resource(R: int, N: int, M: int = 1,
                           data_width: int = 16, taps: int = 21) -> dict:
    """
    估算 CIC+FIR 在 FPGA 上的资源占用

    估算公式 (来自项目已有逻辑):
    - CIC LUTs ≈ internal_width * N * 1.5
    - CIC FFs  ≈ internal_width * N * 2
    - FIR DSPs = ceil(taps / 2)  (利用偶对称预加法器优化)
    - FIR LUTs ≈ taps * 15
    - FIR FFs  ≈ taps * data_width + 50

    Args:
        R: 抽取/插值比
        N: CIC 级数
        M: 微分延迟
        data_width: 输入数据位宽
        taps: FIR 抽头数

    Returns:
        dict: 资源估算报告
    """
    est = fir_calc.estimate_fpga_resource(N, M, R, data_width, taps)

    # 资源等级
    total_dsps = est["total"]["dsps"]
    total_luts = est["total"]["luts"]
    if total_dsps <= _RESOURCE_LIGHT_DSPS and total_luts <= _RESOURCE_LIGHT_LUTS:
        grade = "轻量"
    elif total_dsps <= _RESOURCE_MED_DSPS and total_luts <= _RESOURCE_MED_LUTS:
        grade = "中等"
    elif total_dsps <= _RESOURCE_HEAVY_DSPS and total_luts <= _RESOURCE_HEAVY_LUTS:
        grade = "偏重"
    else:
        grade = "重"

    est["resource_grade"] = grade
    return est


# ==============================================================================
# Tool 5: MATLAB 验证脚本生成 (MATLAB Script Generation)
# ==============================================================================

def generate_matlab_script(R: int, N: int, M: int = 1,
                           taps: int = 21, passband_ratio: float = 0.5,
                           script_type: str = "freq_response") -> dict:
    """
    生成 MATLAB/Octave 验证脚本

    Args:
        R: 抽取/插值比
        N: CIC 级数
        M: 微分延迟
        taps: FIR 抽头数
        passband_ratio: FIR 通带比例
        script_type: "freq_response" | "impulse_test" | "snr_analysis"

    Returns:
        dict: {
            "script": str,       — MATLAB 脚本内容
            "filename": str,     — 建议文件名
            "description": str   — 脚本功能描述
        }
    """
    if script_type == "freq_response":
        script = _gen_matlab_freq_response(R, N, M, taps, passband_ratio)
        filename = "cic_verify_freq.m"
        desc = "CIC+FIR 级联频率响应验证脚本，绘制通带和阻带特性曲线"

    elif script_type == "impulse_test":
        script = _gen_matlab_impulse(R, N, M)
        filename = "cic_impulse_test.m"
        desc = "CIC 冲激响应测试脚本，验证滤波器行为"

    elif script_type == "snr_analysis":
        script = _gen_matlab_snr(R, N, M)
        filename = "cic_snr_analysis.m"
        desc = "CIC 信噪比分析脚本，评估量化噪声影响"

    else:
        return {"error": f"不支持的脚本类型: {script_type}"}

    return {
        "script": script,
        "filename": filename,
        "description": desc
    }


def _matlab_header(R: int, N: int, M: int, extra: str = "") -> str:
    """Generate common MATLAB script header."""
    return f"""clear; close all; clc;

R = {R};          % 抽取/插值比
N = {N};          % CIC 级数
M = {M};          % 微分延迟
{extra}"""


def _matlab_build_filter() -> str:
    """Generate MATLAB CIC filter construction via transfer function."""
    return """%% === 构建 CIC 传递函数 ===
% H(z) = [(1 - z^(-R*M)) / (1 - z^(-1))]^N
b_stage = [1, zeros(1, R*M-1), -1]; % 梳状器
a_stage = [1, -1];                   % 积分器

b = 1; a = 1;
for k = 1:N
    b = conv(b, b_stage);
    a = conv(a, a_stage);
end"""


def _gen_matlab_freq_response(R: int, N: int, M: int,
                               taps: int, pb_ratio: float) -> str:
    """生成频率响应验证 MATLAB 脚本"""
    extra = """Fs_in = 1;        % 归一化输入采样率
Fs_out = Fs_in/R; % 输出采样率"""
    return f"""%% CIC + FIR 频率响应验证
%% 自动生成 — 参数: R={R}, N={N}, M={M}, FIR_Taps={taps}
%% 使用方法: 在 MATLAB/Octave 中直接运行

{_matlab_header(R, N, M, extra)}

%% === CIC 频率响应 ===
num_points = 4096;
f = linspace(0, 0.5, num_points);  % 归一化频率 (相对 Fs_in)
w = 2 * pi * f;

% CIC 传递函数: H(z) = [(1 - z^(-R*M)) / (1 - z^(-1))]^N
H_cic = zeros(size(f));
for k = 1:num_points
    if f(k) == 0
        H_cic(k) = 1;
    else
        num = sin(pi * R * M * f(k));
        den = R * sin(pi * M * f(k));
        H_cic(k) = abs(num / den)^N;
    end
end

H_cic_db = 20*log10(H_cic + eps);

%% === FIR 补偿滤波器 (理想反函数) ===
pb_end = 0.5/R * {pb_ratio};     % 通带边界 (归一化)
pb_idx = round(pb_end / 0.5 * num_points);
if pb_idx < 1, pb_idx = 1; end

H_target = zeros(size(f));
H_target(1:pb_idx) = 1 ./ (H_cic(1:pb_idx) + eps);

%% === 绘图 ===
figure('Name', 'CIC 频率响应验证', 'Position', [100 100 900 600]);

subplot(2,1,1);
plot(f, H_cic_db, 'b-', 'LineWidth', 1.5);
hold on;
xline(0.5/R, 'r--', 'Fout/2 (Nyquist)', 'LineWidth', 1);
xline(pb_end, 'g--', '通带边界', 'LineWidth', 1);
xlabel('归一化频率 (×Fs_in)');
ylabel('幅度 (dB)');
title(sprintf('CIC 频率响应 (R=%d, N=%d, M=%d)', R, N, M));
grid on; ylim([-120 5]);
legend('CIC', 'Nyquist', '通带边界');

subplot(2,1,2);
% 通带细节
f_pb = f(1:pb_idx*3);
plot(f_pb, H_cic_db(1:pb_idx*3), 'b-', 'LineWidth', 1.5);
xlabel('归一化频率 (×Fs_in)');
ylabel('幅度 (dB)');
title('通带细节 (Passband Droop)');
grid on;

fprintf('通带边缘衰减: %.2f dB\\n', H_cic_db(pb_idx));
fprintf('位宽增长: %d bits\\n', N * ceil(log2(R*M)));
fprintf('阻带抑制 (@Fs_out/2): ~%d dB\\n', N * 13);
"""


def _gen_matlab_impulse(R: int, N: int, M: int) -> str:
    """生成冲激响应测试 MATLAB 脚本"""
    return f"""%% CIC 冲激响应测试
%% 参数: R={R}, N={N}, M={M}

{_matlab_header(R, N, M)}

{_matlab_build_filter()}

%% === 冲激响应 ===
imp_len = R * M * N * 3;
impulse = [1, zeros(1, imp_len-1)];
y = filter(b, a, impulse);

figure('Name', 'CIC 冲激响应');
stem(0:length(y)-1, y, 'b.', 'MarkerSize', 4);
xlabel('采样点'); ylabel('幅度');
title(sprintf('CIC 冲激响应 (R=%d, N=%d, M=%d)', R, N, M));
grid on;

fprintf('冲激响应长度: %d 个采样\\n', length(find(y ~= 0)));
fprintf('最大值: %d\\n', max(y));
"""


def _gen_matlab_snr(R: int, N: int, M: int) -> str:
    """生成 SNR 分析 MATLAB 脚本"""
    return f"""%% CIC 信噪比分析
%% 参数: R={R}, N={N}, M={M}

{_matlab_header(R, N, M)}

{_matlab_build_filter()}

%% === 不同位宽下的 SNR 分析 ===
data_widths = [8 12 16 24 32];  % 待分析的输入位宽
fprintf('=== CIC SNR 分析 (R=%d, N=%d, M=%d) ===\\n', R, N, M);
fprintf('%-12s %-12s %-12s %-12s\\n', '输入位宽', '位宽增长', '内部位宽', '理论SNR');
fprintf('%s\\n', repmat('-', 1, 50));

for w = data_widths
    growth = N * ceil(log2(R*M));
    internal_w = w + growth;
    snr_ideal = 6.02 * w + 1.76;  % 理想 SNR
    
    % CIC 处理增益 (抽取时)
    process_gain_db = 10*log10(R);
    
    fprintf('%-12d %-12d %-12d %-12.1f dB\\n', w, growth, internal_w, snr_ideal + process_gain_db);
end

fprintf('\\n注: 理论SNR = 6.02*位宽 + 1.76 + 10*log10(R)\\n');
fprintf('实际SNR还受截断模式和FIR补偿的影响\\n');
"""


# ==============================================================================
# Tool 6: UVM 测试场景建议 (UVM Scenario Suggestion)
# ==============================================================================

def suggest_uvm_scenarios(R: int, N: int, M: int = 1,
                          data_width: int = 16,
                          mode: str = "decimation") -> dict:
    """
    根据设计参数，建议需要覆盖的 UVM 测试场景

    Args:
        R: 抽取/插值比
        N: CIC 级数
        M: 微分延迟
        data_width: 数据位宽
        mode: "decimation" | "interpolation"

    Returns:
        dict: {
            "critical_scenarios": list[dict],
            "coverage_points": list[str],
            "total_scenarios": int
        }
    """
    max_val = 2 ** (data_width - 1) - 1
    min_val = -(2 ** (data_width - 1))
    bit_growth = calc_cic_growth(N, M, R)
    internal_width = data_width + bit_growth

    scenarios: list[dict] = []

    # 1. 基本功能验证
    scenarios.append({
        "name": "零输入测试",
        "priority": "P0",
        "description": "连续发送全零数据，验证输出保持为零",
        "stimulus": f"发送 {R * 10} 个零值采样",
        "expected": "所有输出均为 0"
    })

    scenarios.append({
        "name": "满量程正值测试",
        "priority": "P0",
        "description": f"连续发送最大正值 ({max_val})，检查内部 {internal_width}-bit 寄存器是否溢出",
        "stimulus": f"连续发送 {max_val} 共 {R * N * 5} 个采样",
        "expected": "输出应稳定且在合法范围"
    })

    scenarios.append({
        "name": "满量程负值测试",
        "priority": "P0",
        "description": f"连续发送最小负值 ({min_val})，检查有符号数处理",
        "stimulus": f"连续发送 {min_val} 共 {R * N * 5} 个采样",
        "expected": "输出应稳定且在合法范围"
    })

    # 2. 正弦波测试
    scenarios.append({
        "name": "通带正弦波通过测试",
        "priority": "P0",
        "description": "输入通带内正弦信号，验证信号能通过且衰减在规格内",
        "stimulus": f"生成频率为 Fout/4 的正弦波，持续 {R * 100} 个输入采样",
        "expected": "输出正弦波幅度衰减 < 1dB"
    })

    scenarios.append({
        "name": "阻带正弦波抑制测试",
        "priority": "P1",
        "description": "输入阻带内正弦信号，验证信号被充分衰减",
        "stimulus": "生成频率为 Fout*0.75 的正弦波",
        "expected": f"输出信号衰减 > {N * 13}dB"
    })

    # 3. 复位与边界测试
    scenarios.append({
        "name": "复位测试",
        "priority": "P0",
        "description": "在数据流中间触发复位，验证所有内部状态清零",
        "stimulus": "先发送100个有效数据，然后拉低reset，再恢复",
        "expected": "复位后所有积分器和梳状器寄存器归零"
    })

    scenarios.append({
        "name": "突变信号测试",
        "priority": "P1",
        "description": f"输入从 0 跳变到 {max_val}，验证阶跃响应",
        "stimulus": f"前 {R * 5} 个采样为 0，后 {R * 5} 个采样为 {max_val}",
        "expected": f"输出应在 {N * M} 个输出采样周期后稳定"
    })

    # 4. 正负交替测试
    scenarios.append({
        "name": "交替极性测试",
        "priority": "P1",
        "description": "输入 +max/-max 交替信号（高频成分），验证阻带衰减",
        "stimulus": f"+{max_val}, {min_val} 交替发送 {R * 20} 个采样",
        "expected": "输出应接近零（交替信号是高频分量）"
    })

    # 5. 特定于模式的场景
    if mode == "decimation":
        scenarios.append({
            "name": "数据有效性 (valid) 信号测试",
            "priority": "P1",
            "description": f"验证 valid_o 每 {R} 个输入时钟周期拉高一次",
            "stimulus": "连续数据输入",
            "expected": f"valid_o 周期恰好为 {R} 个 clk 周期"
        })
    else:
        scenarios.append({
            "name": "插值零填充验证",
            "priority": "P1",
            "description": f"验证每个输入采样之间插入 {R - 1} 个零",
            "stimulus": "单个脉冲输入",
            "expected": f"输出应呈现 {R} 倍展开的冲激响应"
        })

    # 覆盖率要点
    coverage = [
        f"toggle_coverage: 所有 {internal_width}-bit 内部寄存器的位翻转覆盖率",
        f"functional: 输入数据符号位 (正/负/零) 的组合覆盖",
        f"functional: 连续 {R}  个输入采样中数据变化模式",
        "functional: 复位时序 (复位中、复位前一拍、复位后一拍)",
        f"functional: 满量程边界值 ({max_val}, {min_val}, 0, 1, -1)",
    ]

    if bit_growth > 24:
        scenarios.append({
            "name": "位宽增长压力测试",
            "priority": "P0",
            "description": f"位宽增长 {bit_growth} bits 较大，需专项验证内部寄存器不溢出",
            "stimulus": "构造使积分器单调递增的输入序列",
            "expected": f"内部 {internal_width}-bit 寄存器在二补码范围内"
        })
        coverage.append(f"assertion: 内部寄存器值不应超过 {internal_width}-bit 有符号范围")

    return {
        "critical_scenarios": scenarios,
        "coverage_points": coverage,
        "total_scenarios": len(scenarios)
    }


# ==============================================================================
# Tool 7: 测试平台生成 (Testbench Generation)
# ==============================================================================

def generate_testbench_tool(params: dict) -> dict:
    """
    根据设计参数生成 Python 参考模型测试脚本

    Args:
        params: 设计参数字典，需包含 type, data_w, ratio, stages, delay 等键

    Returns:
        dict: {
            "files_created": list[str],
            "summary": str
        }
    """
    try:
        from tb_generator import generate_testbench
    except ImportError as e:
        return {"error": f"tb_generator module not found: {e}"}

    import tempfile
    output_dir = params.get('path', tempfile.gettempdir())
    return generate_testbench(params, output_dir)


# ==============================================================================
# Tool 7: Natural language -> candidate design params (wraps LLMHelper)
# ==============================================================================

_FS_UNIT_MAP = {"hz": 1.0, "khz": 1e3, "mhz": 1e6, "ghz": 1e9}


def _extract_fs_hint_from_text(text: str):
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(Hz|kHz|MHz|GHz|hz|khz|mhz|ghz)", text)
    if not m:
        return None
    try:
        return float(m.group(1)) * _FS_UNIT_MAP[m.group(2).lower()]
    except (ValueError, KeyError):
        return None


def _fallback_params(description: str) -> dict:
    """Rule-based fallback when the LLM suggestion fails.

    Extracts the two sample rates ("A kHz 转 B kHz"), derives the ratio and
    mode from keywords, and returns a conservative default design.
    """
    desc_l = description.lower()
    # find frequency pairs like "48kHz 转 8kHz" / "48 kHz to 8 kHz"
    pairs = re.findall(r"(\d+(?:\.\d+)?)\s*(hz|khz|mhz|ghz)", desc_l)
    ratio = None
    fs_in = None
    if len(pairs) >= 2:
        try:
            f0 = float(pairs[0][0]) * _FS_UNIT_MAP[pairs[0][1].lower()]
            f1 = float(pairs[1][0]) * _FS_UNIT_MAP[pairs[1][1].lower()]
            fs_in = max(f0, f1)
            if f0 > 0 and f1 > 0:
                ratio = int(round(max(f0, f1) / min(f0, f1)))
                ratio = max(2, min(8192, ratio))
        except (ValueError, KeyError, IndexError):
            ratio = None

    is_upsample = any(k in desc_l for k in ("升采样", "升频", "插值", "upsample", "up-convert", "interpolat", "放大", "上采样"))
    is_image = any(k in desc_l for k in ("png", "图像", "灰度", "像素", "image", "4x", "4×"))
    if ratio is None:
        ratio = 4  # common demo ratio
    mode = "Interpolator_FIR" if is_upsample else "Decimator_FIR"
    if is_upsample and is_image:
        mode = "Interpolator_FIR"

    return {
        "mode":           mode,
        "ratio":          ratio,
        "stages":         3,
        "delay":          1,
        "fir_taps":       21,
        "passband_ratio": 0.35 if is_image else 0.5,
        "fir_type":       "parallel",
        "data_width":     8 if is_image else 16,
        "fs_in":          fs_in if fs_in is not None else (10000000 if is_image else None),
        "reasoning":      "规则兜底: LLM 参数建议失败，使用从需求文本提取的保守参数（可在 UI 中手动微调）",
    }


def suggest_design_params(description: str) -> dict:
    if not isinstance(description, str) or not description.strip():
        return {"error": "description is empty"}

    try:
        from llm_helper import LLMHelper
        helper = LLMHelper()
        if not helper.is_configured():
            return {"error": "LLM API_KEY not configured"}
        raw = helper.suggest_params(description)
    except Exception as e:
        fallback = _fallback_params(description)
        fallback["warning"] = f"LLM 参数建议失败({e})，已使用规则兜底参数"
        return fallback

    if not isinstance(raw, dict):
        return {"error": f"LLM returned non-dict: {type(raw).__name__}"}

    fs_hint = _extract_fs_hint_from_text(description)
    desc_l = description.lower()
    is_image_4x = (
        any(k in desc_l for k in ("png", "4x", "4×"))
        or any(k in description for k in ("图像", "灰度", "像素", "放大"))
    ) and ("4" in desc_l or "4x" in desc_l or "4×" in desc_l)
    mode = raw.get("mode", "Decimator_FIR")
    if is_image_4x and mode == "Interpolator":
        mode = "Interpolator_FIR"

    result: dict[str, Any] = {
        "mode":           mode,
        "ratio":          raw.get("ratio") or 4,
        "stages":         raw.get("stages") or 3,
        "delay":          raw.get("delay") or 1,
        "fir_taps":       raw.get("fir_taps") or 21,
        "passband_ratio": raw.get("passband_ratio") or 0.5,
        "fir_type":       raw.get("fir_type") or "parallel",
        "data_width":     raw.get("data_width") or (8 if is_image_4x else 16),
        "fs_in":          raw.get("fs_in") or fs_hint,
        "reasoning":      raw.get("reasoning", ""),
    }
    if is_image_4x and result["fs_in"] is None:
        result["fs_in"] = 10000000
    if raw.get("warnings"):
        result["warnings"] = raw["warnings"]
    if raw.get("alternatives"):
        result["alternatives"] = raw["alternatives"]
    return result


# ==============================================================================
# 工具注册表 (Tool Registry)
# ==============================================================================

TOOL_REGISTRY: list[dict[str, Any]] = [
    {
        "name": "calc_bit_growth",
        "description": "计算CIC滤波器的位宽增长量，评估资源开销。当需要判断设计是否会导致过大的寄存器宽度时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "R":          {"type": "integer", "description": "抽取/插值比 (2~8192)"},
                "N":          {"type": "integer", "description": "CIC级数 (1~8)"},
                "M":          {"type": "integer", "description": "微分延迟 (1~4, 默认1)"},
                "data_width": {"type": "integer", "description": "输入数据位宽 (4~64, 默认16)"},
            },
            "required": ["R", "N"]
        },
        "function": calc_bit_growth
    },
    {
        "name": "simulate_freq_response",
        "description": "数值仿真CIC+FIR级联频率响应，返回通带droop、阻带衰减等关键指标。当需要评估设计的滤波性能时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "R":              {"type": "integer", "description": "抽取/插值比"},
                "N":              {"type": "integer", "description": "CIC级数"},
                "M":              {"type": "integer", "description": "微分延迟 (默认1)"},
                "taps":           {"type": "integer", "description": "FIR补偿滤波器抽头数 (奇数)"},
                "passband_ratio": {"type": "number",  "description": "FIR通带比例 (0.1~0.9)"},
                "coeff_width":    {"type": "integer", "description": "FIR系数位宽 (默认16)"},
            },
            "required": ["R", "N"]
        },
        "function": simulate_freq_response
    },
    {
        "name": "check_param_constraints",
        "description": "检查一组设计参数是否在合法范围内，是否满足约束条件（如taps必须为奇数）。当需要验证参数合法性时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "params": {"type": "object", "description": "待检查的参数字典，支持的键: ratio, stages, delay, data_width, fir_taps, passband_ratio, coeff_width"}
            },
            "required": ["params"]
        },
        "function": check_param_constraints
    },
    {
        "name": "estimate_fpga_resource",
        "description": "估算CIC+FIR在FPGA上的资源占用(LUTs/FFs/DSPs)。当需要评估硬件资源开销时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "R":          {"type": "integer", "description": "抽取/插值比"},
                "N":          {"type": "integer", "description": "CIC级数"},
                "M":          {"type": "integer", "description": "微分延迟 (默认1)"},
                "data_width": {"type": "integer", "description": "输入数据位宽 (默认16)"},
                "taps":       {"type": "integer", "description": "FIR抽头数 (默认21)"},
            },
            "required": ["R", "N"]
        },
        "function": estimate_fpga_resource
    },
    {
        "name": "generate_matlab_script",
        "description": "生成MATLAB/Octave验证脚本，用于独立验证CIC滤波器设计。当用户需要MATLAB仿真代码或需要验证设计正确性时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "R":              {"type": "integer", "description": "抽取/插值比"},
                "N":              {"type": "integer", "description": "CIC级数"},
                "M":              {"type": "integer", "description": "微分延迟 (默认1)"},
                "taps":           {"type": "integer", "description": "FIR抽头数 (默认21)"},
                "passband_ratio": {"type": "number",  "description": "FIR通带比例 (默认0.5)"},
                "script_type":    {"type": "string",  "description": "脚本类型: freq_response | impulse_test | snr_analysis"}
            },
            "required": ["R", "N"]
        },
        "function": generate_matlab_script
    },
    {
        "name": "suggest_uvm_scenarios",
        "description": "根据设计参数和架构(抽取/插值)，建议需要覆盖的UVM验证测试场景和覆盖率要求。当需要规划验证策略时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "R":          {"type": "integer", "description": "抽取/插值比"},
                "N":          {"type": "integer", "description": "CIC级数"},
                "M":          {"type": "integer", "description": "微分延迟 (默认1)"},
                "data_width": {"type": "integer", "description": "数据位宽 (默认16)"},
                "mode":       {"type": "string",  "description": "架构模式: decimation | interpolation"}
            },
            "required": ["R", "N"]
        },
        "function": suggest_uvm_scenarios
    },
    {
        "name": "generate_testbench",
        "description": "根据当前设计参数生成Python参考模型测试脚本(脉冲/正弦/阶跃)。当用户需要测试平台或验证脚本时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "params": {"type": "object", "description": "设计参数字典，需包含 type, data_w, ratio, stages, delay 等键"}
            },
            "required": ["params"]
        },
        "function": generate_testbench_tool
    },
    {
        "name": "suggest_design_params",
        "description": "当用户以自然语言描述设计需求（给出采样率、抽取/插值比、带宽、通带纹波、阻带衰减等性能指标）时调用；返回一组候选参数，可直接送入 check_param_constraints / simulate_freq_response 验证，也可作为 Final Answer JSON 的基础。返回字段: mode, ratio, stages, delay, fir_taps, passband_ratio, fir_type, data_width, fs_in, reasoning。失败时返回 {\"error\": ...}。",
        "parameters": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "用户用自然语言描述的设计需求，例如: '48kHz 转 192kHz 升采样，通带纹波 0.1dB，阻带 -80dB'"}
            },
            "required": ["description"]
        },
        "function": suggest_design_params
    },
]
