# src_generator.py
# CIC RTL 代码生成器，使用基于经过验证的 rtl/ 实现的新版硬模板

import datetime
import os
import re
import fir_calc

# 导入模板
from src_templates import (
    DECIMATOR_TEMPLATE, 
    INTERPOLATOR_TEMPLATE, 
    FIR_P_TEMPLATE,
    FIR_S_TEMPLATE,
    FIR_M_TEMPLATE,
    CIC_DEC_FIR_P_TOP_TEMPLATE,
    CIC_DEC_FIR_S_TOP_TEMPLATE,
    CIC_DEC_FIR_M_TOP_TEMPLATE, 
    FIR_P_CIC_INT_TOP_TEMPLATE, 
    FIR_S_CIC_INT_TOP_TEMPLATE,
    FIR_M_CIC_INT_TOP_TEMPLATE,
    DECIMATOR_TB_TEMPLATE,
    INTERPOLATOR_TB_TEMPLATE
)

# 尝试导入 FIR 计算模块
HAS_LIBS = False
IMPORT_ERR_MSG = ""

try:
    from fir_calc import calculate_fir_params
    HAS_LIBS = True
except ImportError as e:
    HAS_LIBS = False
    IMPORT_ERR_MSG = str(e)
except Exception as e:
    HAS_LIBS = False
    IMPORT_ERR_MSG = f"Unknown Error: {str(e)}"

class CICCodeGenerator:
    """
    CIC 滤波器 RTL 代码生成器 (基于验证后的 rtl/ 模板)
    """
    
    def __init__(self, params):
        """
        使用参数字典初始化生成器
        """
        self.params = params
        self.raw_name = os.path.splitext(params.get('filename', 'cic_gen'))[0]
        self.generate_tb = params.get('generate_tb', False)
        
        # 获取 fir_type: parallel (默认) | serial | da
        fir_type_str = params.get('fir_type', 'parallel').lower()
        if 'serial' in fir_type_str or '串行' in fir_type_str:
            self.fir_type = 'serial'
        elif 'da' in fir_type_str or '分布式' in fir_type_str:
            self.fir_type = 'da'
        else:
            self.fir_type = 'parallel'  # 默认为并联结构
    
    def _calc_cic_growth(self):
        """计算 CIC 位宽增长"""
        return fir_calc.calc_cic_growth(
            self.params['stages'],
            self.params.get('delay', 1),
            self.params['ratio']
        )
    
    def generate(self):
        """根据配置的模式生成 RTL 代码"""
        mode = self.params['type']

        # Handle output_width for custom precision
        output_width = self.params.get('output_width')
        use_custom_output_width = output_width is not None and output_width > 0

        # Calculate DATA_OUT_W expression
        data_w = self.params['data_w']
        ratio = self.params['ratio']
        stages = self.params['stages']
        delay = self.params.get('delay', 1)

        # Reset style context for TB templates
        reset_style = self.params.get('reset_style', 'xilinx')
        if reset_style in ('altera', 'asic'):
            reset_ctx = {"reset_signal": "rst_n", "reset_active": "0", "reset_inactive": "1"}
        else:
            reset_ctx = {"reset_signal": "rst", "reset_active": "1", "reset_inactive": "0"}

        # Common context for all templates
        common_ctx = {
            "module_name": self.raw_name,
            "filename": self.raw_name + ".v",
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data_w": data_w,
            "ratio": ratio,
            "stages": stages,
            "delay": delay,
            "use_custom_output_width": use_custom_output_width,
            "output_width": output_width if use_custom_output_width else 0,
            **reset_ctx,
        }

        # Determine DATA_OUT_W expression based on mode and custom width
        # These will be used in templates and also for FIR submodules
        if use_custom_output_width:
            # Use custom width for standalone outputs and top-level combo outputs
            common_ctx['cic_dec_out_expr'] = str(output_width)
            common_ctx['cic_int_out_expr'] = str(output_width)
            common_ctx['fir_out_expr'] = str(output_width)
            common_ctx['cic_fir_out_expr'] = str(output_width)  # CIC -> FIR
            common_ctx['fir_cic_out_expr'] = str(output_width)   # FIR -> CIC
        else:
            # Use default formula
            common_ctx['cic_dec_out_expr'] = "DATA_IN_W + $clog2((R*M)**N)"
            common_ctx['cic_int_out_expr'] = "DATA_IN_W + (N > $clog2(((R*M)**N)/R) ? N : $clog2(((R*M)**N)/R))"
            common_ctx['fir_out_expr'] = "DATA_IN_W + $clog2(TAP)"
            common_ctx['cic_fir_out_expr'] = "CIC_OUT_W + $clog2(TAP)"
            common_ctx['fir_cic_out_expr'] = "FIR_OUT_W + (N > $clog2(((R*M)**N)/R) ? N : $clog2(((R*M)**N)/R))"

        # Note: in combo modes (e.g. Decimator_FIR), the sub-modules need to be
        # generated with full precision. We override their DATA_OUT_W explicitly
        # in the respective generation methods.

        if mode == 'Decimator':
            code = self._generate_decimator(common_ctx)
        elif mode == 'Interpolator':
            code = self._generate_interpolator(common_ctx)
        elif mode == 'Decimator_FIR':
            code = self._generate_decimator_fir(common_ctx)
        elif mode == 'Interpolator_FIR':
            code = self._generate_interpolator_fir(common_ctx)
        else:
            return f"// [ERROR] Unknown mode: {mode}"

        # Post-process: apply reset style transformation
        return self._apply_reset_style(code, reset_style)
    
    @staticmethod
    def _apply_reset_style(code, style):
        """
        Post-process generated RTL to apply the chosen reset style.
        Templates use Xilinx style (sync active-high rst) by default.

        Styles:
            xilinx: no change (sync active-high rst)
            altera: sync active-low rst_n
            asic:   async active-low rst_n with sync release
        """
        if style == 'xilinx' or style == 'sync_high':
            return code

        # Altera & ASIC: rename rst → rst_n, flip polarity
        # Port declaration: "input   wire ... rst," → "input   wire ... rst_n,"
        code = re.sub(r'\brst\b', 'rst_n', code)
        # Reset condition: "if (rst_n)" → "if (!rst_n)"
        code = re.sub(r'if\s*\(\s*rst_n\s*\)', 'if (!rst_n)', code)

        if style == 'asic':
            # Add async reset to sensitivity list for always blocks that contain reset
            # Match: "always @(posedge clk) begin" followed by "if (!rst_n)"
            # Replace with: "always @(posedge clk or negedge rst_n) begin"
            code = re.sub(
                r'always\s+@\s*\(\s*posedge\s+clk\s*\)\s+begin(\s+if\s*\(\s*!rst_n\s*\))',
                r'always @(posedge clk or negedge rst_n) begin\1',
                code
            )

        return code

    def _generate_decimator(self, ctx):
        """生成 CIC 抽取器代码"""
        code = DECIMATOR_TEMPLATE.format(**ctx)
        if self.generate_tb:
            code += "\n\n" + DECIMATOR_TB_TEMPLATE.format(**ctx)
        return code
    
    def _generate_interpolator(self, ctx):
        """生成 CIC 插值器代码"""
        code = INTERPOLATOR_TEMPLATE.format(**ctx)
        if self.generate_tb:
            code += "\n\n" + INTERPOLATOR_TB_TEMPLATE.format(**ctx)
        return code

    def _format_fir_coeffs(self, fir_type, coeffs_list):
        taps = len(coeffs_list)
        lines = []
        if fir_type == 'parallel':
            # 并联结构利用对称性只存一半
            half = (taps + 1) // 2
            for i in range(half):
                lines.append(f"assign coe[{i}] = {coeffs_list[i]};")
        else:
            # 串联结构和 DA 结构全存
            for i in range(taps):
                lines.append(f"assign coe[{i}] = {coeffs_list[i]};")
        # 增加一些缩进使生成的代码美观
        return "\n".join("    " + line for line in lines)
    
    def _generate_decimator_fir(self, ctx):
        """生成 CIC 抽取器 + FIR 补偿滤波器"""
        
        if not HAS_LIBS:
            return f"// [ERROR] Libraries missing: {IMPORT_ERR_MSG}"
        
        try:
            win_type = self.params.get('window', 'hamming')
            is_antisym = self.params.get('antisym', False)
            
            # Calculate FIR input width (CIC output width)
            cic_growth = self._calc_cic_growth()
            fir_input_w = self.params['data_w'] + cic_growth
            
            best_shift, verilog_coeffs_list = calculate_fir_params(
                N=self.params['stages'],
                R=self.params['ratio'],
                M=self.params.get('delay', 1),
                taps=self.params['fir_taps'],
                passband_ratio=self.params['fir_passband'],
                coeff_width=self.params['fir_width'],
                window_type=win_type,
                antisymmetric=is_antisym,
                response_mode='decimator'
            )
            
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            return f"// [ERROR] FIR Calculation Failed:\n// {str(e)}\n\n/*\n{tb}\n*/"
        
        fir_coeffs_str = self._format_fir_coeffs(self.fir_type, verilog_coeffs_list)
        
        cic_sub_name = self.raw_name + "_cic_dec"
        fir_sub_name = self.raw_name + "_fir"
        
        top_ctx = ctx.copy()
        top_ctx.update({
            "cic_module_name": cic_sub_name,
            "fir_module_name": fir_sub_name,
            "taps": self.params['fir_taps'],
            "fir_width": self.params['fir_width'],
            "fir_scale_w": str(best_shift)
        })
        
        # 选择相应的模板
        if self.fir_type == 'serial':
            top_tpl = CIC_DEC_FIR_S_TOP_TEMPLATE
            fir_tpl = FIR_S_TEMPLATE
        elif self.fir_type == 'da':
            top_tpl = CIC_DEC_FIR_M_TOP_TEMPLATE
            fir_tpl = FIR_M_TEMPLATE
        else: # parallel
            top_tpl = CIC_DEC_FIR_P_TOP_TEMPLATE
            fir_tpl = FIR_P_TEMPLATE
            
        # 生成顶层模块
        top_code = top_tpl.format(**top_ctx)
        
        # 生成 CIC 子模块
        cic_ctx = ctx.copy()
        cic_ctx["module_name"] = cic_sub_name
        cic_ctx["cic_dec_out_expr"] = "DATA_IN_W + $clog2((R*M)**N)"  # Always full precision for sub-module
        cic_code = DECIMATOR_TEMPLATE.format(**cic_ctx)
        
        # 生成 FIR 子模块
        fir_ctx = top_ctx.copy()
        fir_ctx["module_name"] = fir_sub_name
        fir_ctx["data_in_w"] = fir_input_w
        fir_ctx["fir_coeffs_assignments"] = fir_coeffs_str
        fir_ctx["fir_out_expr"] = "DATA_IN_W + $clog2(TAP)"  # Always full precision for sub-module
        fir_ctx["fir_scale_w"] = str(best_shift)  # output scaling matches coefficient shift
        fir_code = fir_tpl.format(**fir_ctx)
        
        full_code = top_code + "\n\n" + cic_code + "\n\n" + fir_code
        
        if self.generate_tb:
            tb_ctx = ctx.copy()
            tb_ctx["module_name"] = self.raw_name
            full_code += "\n\n" + DECIMATOR_TB_TEMPLATE.format(**tb_ctx)
        
        return full_code
    
    def _generate_interpolator_fir(self, ctx):
        """生成 FIR 预补偿 + CIC 插值器"""
        
        if not HAS_LIBS:
            return f"// [ERROR] Libraries missing: {IMPORT_ERR_MSG}"
        
        try:
            win_type = self.params.get('window', 'hamming')
            is_antisym = self.params.get('antisym', False)
            
            best_shift, verilog_coeffs_list = calculate_fir_params(
                N=self.params['stages'],
                R=self.params['ratio'],
                M=self.params.get('delay', 1),
                taps=self.params['fir_taps'],
                passband_ratio=self.params['fir_passband'],
                coeff_width=self.params['fir_width'],
                window_type=win_type,
                antisymmetric=is_antisym,
                response_mode='interpolator'
            )
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            return f"// [ERROR] FIR Calculation Failed:\n// {str(e)}\n\n/*\n{tb}\n*/"
        
        fir_coeffs_str = self._format_fir_coeffs(self.fir_type, verilog_coeffs_list)
        
        cic_sub_name = self.raw_name + "_cic_int"
        fir_sub_name = self.raw_name + "_fir"
        
        top_ctx = ctx.copy()
        top_ctx.update({
            "cic_module_name": cic_sub_name,
            "fir_module_name": fir_sub_name,
            "taps": self.params['fir_taps'],
            "fir_width": self.params['fir_width'],
            "fir_scale_w": str(best_shift)
        })
        
        # 选择相应的模板
        if self.fir_type == 'serial':
            top_tpl = FIR_S_CIC_INT_TOP_TEMPLATE
            fir_tpl = FIR_S_TEMPLATE
        elif self.fir_type == 'da':
            top_tpl = FIR_M_CIC_INT_TOP_TEMPLATE
            fir_tpl = FIR_M_TEMPLATE
        else: # parallel
            top_tpl = FIR_P_CIC_INT_TOP_TEMPLATE
            fir_tpl = FIR_P_TEMPLATE
            
        # 生成顶层模块
        top_code = top_tpl.format(**top_ctx)
        
        # 生成 CIC 子模块  
        cic_ctx = ctx.copy()
        cic_ctx["module_name"] = cic_sub_name
        cic_ctx["cic_int_out_expr"] = "DATA_IN_W + (N > $clog2(((R*M)**N)/R) ? N : $clog2(((R*M)**N)/R))"  # Always full precision for sub-module
        cic_code = INTERPOLATOR_TEMPLATE.format(**cic_ctx)
        
        # 生成 FIR 子模块
        fir_ctx = top_ctx.copy()
        fir_ctx["module_name"] = fir_sub_name
        fir_ctx["data_in_w"] = self.params['data_w'] # FIR before CIC uses data_w
        fir_ctx["fir_coeffs_assignments"] = fir_coeffs_str
        fir_ctx["fir_out_expr"] = "DATA_IN_W + $clog2(TAP)"  # Always full precision for sub-module
        fir_ctx["fir_scale_w"] = str(best_shift)  # output scaling matches coefficient shift
        fir_code = fir_tpl.format(**fir_ctx)
        
        full_code = top_code + "\n\n" + cic_code + "\n\n" + fir_code
        
        if self.generate_tb:
            tb_ctx = ctx.copy()
            tb_ctx["module_name"] = self.raw_name
            full_code += "\n\n" + INTERPOLATOR_TB_TEMPLATE.format(**tb_ctx)
        
        return full_code


def generate_single_file(params, filepath):
    """便捷函数: 生成并保存 RTL 代码"""
    generator = CICCodeGenerator(params)
    code = generator.generate()
    
    if code.startswith("// [ERROR]"):
        raise RuntimeError(code)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(code)
    
    return True
