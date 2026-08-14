#!/usr/bin/env python3
"""Generate a single Python test script with Verilog co-simulation for CIC/FIR designs.

The generated script contains:
  1. Python reference model
  2. Verilog testbench generator
  3. Co-simulation runner that compiles, runs, and compares results
"""

import os
import subprocess
import textwrap
import math
import fir_calc
import tempfile
import shutil

# ---------------------------------------------------------------------------
# Reference model templates
# ---------------------------------------------------------------------------

_REF_INTERPOLATE = textwrap.dedent("""\
    def cic_interpolate_ref(y, N, M, R):
        y = list(y)
        # Comb stage
        for i in range(N):
            for j in range(len(y)-1, M-1, -1):
                y[j] = y[j] - y[j-M]
        # Upconvert
        y2 = [0] * (len(y) * R)
        for i in range(len(y)):
            y2[i * R] = y[i]
        y = y2
        # Integrate
        for i in range(N):
            s = 0
            for j in range(len(y)):
                s += y[j]
                y[j] = s
        return y
""")

_REF_DECIMATE = textwrap.dedent("""\
    def cic_decimate_ref(y, N, M, R):
        import numpy as np
        y = np.array(y, dtype=np.int64)
        num_in = len(y)
        int_r = [np.int64(0)] * N
        comb_r = [np.int64(0)] * N
        delay = [[np.int64(0)] * M for _ in range(N)]
        outputs = []
        cycle_cnt = 0
        for idx in range(num_in):
            d = np.int64(y[idx])
            if cycle_cnt == 0:
                outputs.append(int(comb_r[N - 1]))
                new_comb_r = [np.int64(0)] * N
                new_delay = [list(dl) for dl in delay]
                for k in range(N):
                    src = int_r[N - 1] if k == 0 else comb_r[k - 1]
                    new_comb_r[k] = src - delay[k][M - 1]
                    new_delay[k][0] = src
                    for m in range(M - 2, -1, -1):
                        new_delay[k][m + 1] = delay[k][m]
                comb_r = new_comb_r
                delay = new_delay
            new_int_r = list(int_r)
            new_int_r[0] = int_r[0] + d
            for k in range(1, N):
                new_int_r[k] = int_r[k] + int_r[k - 1]
            int_r = new_int_r
            cycle_cnt = cycle_cnt + 1 if cycle_cnt < R - 1 else 0
        return np.array(outputs, dtype=np.int64)
""")

_REF_FIR = textwrap.dedent("""\
    def fir_filter_ref(data, coefficients, coe_w):
        import numpy as np
        data = np.array(data, dtype=np.int64)
        coefficients = np.array(coefficients, dtype=np.int64)
        return (np.convolve(data, coefficients)[:len(data)] >> coe_w)
""")

_REF_DEC_FIR = textwrap.dedent("""\
    def cic_dec_fir_ref(data, N, M, R, coeffs, coe_w):
        cic_out = cic_decimate_ref(data, N, M, R)
        fir_out = fir_filter_ref(cic_out, coeffs, coe_w)
        return fir_out
""")

_REF_FIR_INT = textwrap.dedent("""\
    def fir_cic_int_ref(data, N, M, R, coeffs, coe_w):
        fir_out = fir_filter_ref(data, coeffs, coe_w)
        cic_out = cic_interpolate_ref(fir_out, N, M, R)
        return cic_out
""")

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _is_interpolator(params):
    return params.get("type", "").startswith("Interpolator")

def _has_fir(params):
    return "FIR" in params.get("type", "")

def _calc_output_width(params):
    """Calculate the output width (full precision if custom width not specified)."""
    if params.get('output_width') and params['output_width'] > 0:
        return params['output_width']

    data_w = params['data_w']
    R = params['ratio']
    N = params['stages']
    M = params.get('delay', 1)

    if _is_interpolator(params):
        cic_growth = fir_calc.calc_cic_growth(N, M, R, is_interpolator=True)
    else:
        cic_growth = fir_calc.calc_cic_growth(N, M, R)

    if _has_fir(params):
        tap = params.get('fir_taps', 21)
        fir_growth = int(math.ceil(math.log2(tap)))
        return data_w + cic_growth + fir_growth

    return data_w + cic_growth

def _generate_test_script(params):
    """Generate the complete test script with co-simulation."""
    mode = params['type']
    data_w = params['data_w']
    R = params['ratio']
    N = params['stages']
    M = params.get('delay', 1)
    is_interp = _is_interpolator(params)
    has_fir = _has_fir(params)
    output_w = _calc_output_width(params)
    module_name = params.get('filename', 'cic_gen').replace('.v', '')
    rtl_file_name = module_name + '.v'

    # Determine reference sources and function
    ref_sources = ""
    if is_interp:
        ref_sources += _REF_INTERPOLATE
    else:
        ref_sources += _REF_DECIMATE

    if has_fir:
        ref_sources += _REF_FIR
        if is_interp:
            ref_sources += _REF_FIR_INT
            ref_func = "fir_cic_int_ref"
        else:
            ref_sources += _REF_DEC_FIR
            ref_func = "cic_dec_fir_ref"
        
        # Need FIR coefficients for the reference model
        import fir_calc
        win_type = params.get('window', 'hamming')
        is_antisym = params.get('antisym', False)
        fir_shift, fir_full_coeffs = fir_calc.calculate_fir_params(
            N=N, R=R, M=M, taps=params['fir_taps'],
            passband_ratio=params['fir_passband'],
            coeff_width=params['fir_width'],
            window_type=win_type, antisymmetric=is_antisym
        )
        
        # Parse verilog string to int
        coeffs_int = []
        for c_str in fir_full_coeffs:
            val_str = c_str.split("'sd")[-1]
            val = int(val_str)
            if c_str.startswith("-"):
                val = -val
            coeffs_int.append(val)

        coeffs_def = f"COEFFICIENTS = {coeffs_int}"
        # reference model scales by the same shift the RTL uses (best_shift)
        coe_w_def = f"COE_W = {fir_shift}"
        ref_call = f"{ref_func}(stimulus, N, M, R, COEFFICIENTS, COE_W)"
    else:
        ref_func = "cic_interpolate_ref" if is_interp else "cic_decimate_ref"
        coeffs_def = "COEFFICIENTS = []"
        coe_w_def = "COE_W = 0"
        ref_call = f"{ref_func}(stimulus, N, M, R)"

    # Determine Verilog Testbench
    # Build the DUT instantiation string
    param_list = [
        f".DATA_IN_W({data_w})",
        f".R({R})",
        f".M({M})",
        f".N({N})"
    ]
    if has_fir:
        param_list.append(f".TAP({params['fir_taps']})")
        param_list.append(f".COE_W({params['fir_width']})")
    if params.get('output_width') and params['output_width'] > 0:
        param_list.append(f".DATA_OUT_W({output_w})")

    param_str = ",\\n        ".join(param_list)

    dut_instantiation = f"""\\
    {module_name} #(
        {param_str}
    ) UUT (
        .clk(clk),
        .rst(rst),
        .wdata_i(wdata_i),
        .wvalid_i(wvalid_i),
        .wready_o(wready_o),
        .rdata_o(rdata_o),
        .rvalid_o(rvalid_o),
        .rready_i(rready_i)
    );"""

    flush_count = R * (params.get('fir_taps', 0) + 10) if has_fir else R * 10
    amplitude = 1 << (data_w - 2)

    script = f'''\\
#!/usr/bin/env python3
"""
Auto-generated test script with Verilog co-simulation.
Mode: {mode}
Module: {module_name}
Params: DATA_W={data_w}, R={R}, N={N}, M={M}
"""

import os
import sys
import subprocess
import tempfile
import shutil
import numpy as np

DATA_W = {data_w}
R = {R}
N = {N}
M = {M}
OUTPUT_W = {output_w}
{coe_w_def}
{coeffs_def}

{ref_sources}

def to_unsigned(val, width):
    if val < 0:
        val = val + (1 << width)
    return val & ((1 << width) - 1)

def run_verilog_sim(test_data):
    """Run Verilog simulation and return output data."""
    work_dir = tempfile.mkdtemp()

    try:
        output_file_path = os.path.join(work_dir, "output.txt")
        vcd_file_path = os.environ.get("VCD_FILE", os.path.join(work_dir, "sim.vcd"))
        
        # Create tb_sim.v
        tb_content = """\\
`timescale 1ns/1ps

module tb_sim;

reg clk = 0;
reg rst = 0;

reg [{data_w}-1:0] wdata_i = 0;
reg wvalid_i = 0;
reg rready_i = 0;

wire wready_o;
wire [{output_w}-1:0] rdata_o;
wire rvalid_o;

integer output_file;

// Clock generation
initial begin
    clk = 0;
    forever #5 clk = ~clk;
end

// DUT instantiation
{dut_instantiation}

initial begin
    output_file = $fopen("output.txt", "w");

    $dumpfile("sim.vcd");
    $dumpvars(0, tb_sim);

    rst = 1;
    wvalid_i = 0;
    rready_i = 1;
    #100;
    @(negedge clk);
    rst = 0;
    #100;

"""
        for idx, val in enumerate(test_data):
            uval = to_unsigned(val, {data_w})
            tb_content += f"    @(negedge clk);\\n"
            tb_content += f"    wdata_i = {data_w}'d{{uval}};\\n"
            tb_content += f"    wvalid_i = 1;\\n"
            tb_content += f"    @(negedge clk);\\n"
            tb_content += f"    while (!wready_o) @(negedge clk);\\n"
            tb_content += f"    wvalid_i = 0;\\n\\n"

        flush_count = {flush_count}
        for i in range(flush_count):
            tb_content += f"    @(negedge clk);\\n"
            tb_content += f"    wdata_i = {data_w}'d0;\\n"
            tb_content += f"    wvalid_i = 1;\\n"
            tb_content += f"    @(negedge clk);\\n"
            tb_content += f"    while (!wready_o) @(negedge clk);\\n"
            tb_content += f"    wvalid_i = 0;\\n\\n"

        tb_content += """
    #2000;
    $fclose(output_file);
    // Move VCD if requested
    $finish;
end

// Output logging
always @(posedge clk) begin
    if (rvalid_o && rready_i) begin
        $fdisplay(output_file, "%0t -> %0d", $time, $signed(rdata_o));
    end
end

endmodule
"""
        tb_file = os.path.join(work_dir, "tb_sim.v")
        with open(tb_file, "w") as f:
            f.write(tb_content)

        rtl_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "rtl")
        rtl_file = os.path.join(rtl_dir, "{rtl_file_name}")

        if not os.path.exists(rtl_file):
            print(f"Warning: {{rtl_file}} not found.")
            return []

        vvp_file = os.path.join(work_dir, "sim.vvp")
        compile_cmd = [
            "iverilog", "-g2012", "-o", vvp_file, 
            "-I", rtl_dir,
            rtl_file, tb_file
        ]

        result = subprocess.run(" ".join(compile_cmd), cwd=work_dir, shell=True,
                             capture_output=True, text=True)
        if result.returncode != 0:
            print("Compilation failed:")
            print(result.stderr)
            return []

        run_cmd = ["vvp", vvp_file]
        result = subprocess.run(" ".join(run_cmd), cwd=work_dir, shell=True,
                             capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            print("Simulation failed:")
            print(result.stderr)
            return []

        if os.environ.get("VCD_FILE"):
            shutil.copy(os.path.join(work_dir, "sim.vcd"), os.environ.get("VCD_FILE"))

        output = []
        if os.path.exists(output_file_path):
            with open(output_file_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and " -> " in line:
                        _, val_str = line.split(" -> ")
                        output.append(int(val_str))
        return output

    except subprocess.TimeoutExpired:
        print("Simulation timeout")
        return []
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error: {{e}}")
        return []
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def run_test(name, test_data):
    print(f"\\n{{'=' * 60}}")
    print(f"Test: {{name}}")
    print(f"{{'=' * 60}}")
    
    ref = {ref_call}
    
    if isinstance(ref, np.ndarray):
        ref = ref.tolist()
        
    def to_signed_trunc(val, width):
        val = int(val) & ((1 << width) - 1)
        if val & (1 << (width - 1)):
            val -= (1 << width)
        return val

    ref = [to_signed_trunc(v, OUTPUT_W) for v in ref]

    print(f"  Python ref: {{len(ref)}} samples")

    verilog_out = run_verilog_sim(test_data)

    if not verilog_out:
        print("  FAILED - no Verilog output")
        return False

    print(f"  Verilog: {{len(verilog_out)}} samples")

    vz = np.array(verilog_out, dtype=np.int64)
    rz = np.array(ref, dtype=np.int64)

    match = False
    delay = 0
    search_range = min(100, max(1, len(verilog_out) - len(rz) + 1))
    for d in range(search_range):
        if len(vz[d:d + len(rz)]) == len(rz) and np.array_equal(vz[d:d + len(rz)], rz):
            match = True
            delay = d
            print(f"  Found match at offset {{d}}")
            break

    if match:
        print(f"  PASSED (with {{delay}} sample delay)")
    else:
        print("  FAILED - Mismatch")
        debug_file = f"{{name.replace(' ', '_')}}_debug.txt"
        with open(debug_file, "w") as f:
            f.write(f"=== Debug Trace for {{name}} ===\\n\\n")
            f.write(f"Python Ref ({{len(rz)}} samples):\\n")
            for i, v in enumerate(rz):
                f.write(f"  [{{i}}]: {{v}}\\n")
            f.write(f"\\nVerilog ({{len(vz)}} samples):\\n")
            for i, v in enumerate(vz):
                f.write(f"  [{{i}}]: {{v}}\\n")
        print(f"  >> Dumped debug details to {{debug_file}}")
        best_matches = []
        for d in range(min(100, len(verilog_out))):
            segment = vz[d:d + len(rz)]
            if len(segment) == len(rz):
                diff = segment - rz
                nonzero = np.count_nonzero(diff)
                if nonzero < 10:
                    best_matches.append((d, nonzero))
        if best_matches:
            print(f"  Best matches (offset: mismatches):")
            for d, mismatches in best_matches[:10]:
                print(f"    offset={{d}}: {{mismatches}} mismatches")
        else:
            print(f"  Checking all offsets (vz={{len(vz)}}, rz={{len(rz)}}):")
            for d in range(min(50, len(vz) - len(rz) + 1)):
                segment = vz[d:d + len(rz)]
                if len(segment) == len(rz):
                    diff_count = np.count_nonzero(segment - rz)
                    print(f"    offset={{d}}: {{diff_count}} mismatches")
                else:
                    break
    return match

if __name__ == "__main__":
    results = []
    
    test_impulse = [{amplitude}] + [0] * 50
    stimulus = test_impulse
    results.append(("Impulse", run_test("Impulse", test_impulse)))
    
    test_step = [0] * 5 + [{amplitude}] * 50 + [0] * 20
    stimulus = test_step
    results.append(("Step", run_test("Step", test_step)))
    
    num_samples = 200
    x = np.arange(num_samples)
    test_sine = (np.sin(2 * np.pi * x / num_samples) * {amplitude} // 2).astype(int).tolist()
    stimulus = test_sine
    results.append(("Sine", run_test("Sine", test_sine)))

    print("\\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    all_ok = True
    for name, ok in results:
        print(f"  {{name}}: {{'PASSED' if ok else 'FAILED'}}")
        all_ok = all_ok and ok

    print(f"\\n{{'ALL TESTS PASSED!' if all_ok else 'SOME TESTS FAILED!'}}")
    sys.exit(0 if all_ok else 1)
'''

    return script

def generate_testbench(params, filepath):
    """Generate a single Python test script with co-simulation.

    Args:
        params: dict with keys type, data_w, ratio, stages, delay
        filepath: output .py file path

    Returns:
        {"summary": str}
    """
    script = _generate_test_script(params)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(script)

    mode = params['type']
    R = params['ratio']
    N = params['stages']
    M = params.get('delay', 1)
    data_w = params['data_w']

    summary = (
        f"Generated {mode} test with co-simulation "
        f"(R={R}, N={N}, M={M}, W={data_w})"
    )

    return {"summary": summary}
