# src_templates.py (Generated from verified rtl/ files)

DECIMATOR_TEMPLATE = """
// Language: Verilog 2001

`timescale 1ns/1ps

/*
 * Cascaded Integrator-Comb (CIC) Decimator
 * Architecture: Integrate (N stages) -> Decimate (1:R) -> Comb (N stages)
 */
module {module_name} #(
    parameter DATA_IN_W = {data_w},
    parameter R = {ratio},
    parameter M = {delay},
    parameter N = {stages},
    parameter DATA_OUT_W = {cic_dec_out_expr}
) (
    input   wire                        clk,
    input   wire                        rst,

    input   wire    [DATA_IN_W-1:0]     wdata_i,
    input   wire                        wvalid_i,
    output  wire                        wready_o,

    output  wire    [DATA_OUT_W-1:0]    rdata_o,
    output  wire                        rvalid_o,
    input   wire                        rready_i
);

// Internal full-precision width
localparam FULL_OUT_W = DATA_IN_W + $clog2((R*M)**N);

reg [$clog2(R+1)-1:0] cycle_cnt;

reg [FULL_OUT_W-1:0] int_r    [N-1:0];
reg [FULL_OUT_W-1:0] comb_r [N-1:0];

assign wready_o = rready_i | (cycle_cnt != 0);
assign rdata_o  = FULL_OUT_W > DATA_OUT_W ? comb_r[N-1][DATA_OUT_W-1:0] : comb_r[N-1];
assign rvalid_o = wvalid_i & (cycle_cnt == 0);

genvar k;
integer i;

initial begin
    for (i = 0; i < N; i = i + 1) begin
        int_r[i]    <= 0;
        comb_r[i] <= 0;
    end
end

// Integrator stages: accumulate on every accepted input
generate
for (k = 0; k < N; k = k + 1) begin : integrator
    always @(posedge clk) begin
        if (rst) begin
            int_r[k] <= 0;
        end else begin
            if (wready_o & wvalid_i) begin
                if (k == 0) begin
                    int_r[k] <= $signed(int_r[k]) + $signed(wdata_i);
                end else begin
                    int_r[k] <= $signed(int_r[k]) + $signed(int_r[k-1]);
                end
            end
        end
    end
end
endgenerate

// Comb stages: update on decimated output handshake
generate
for (k = 0; k < N; k = k + 1) begin : comb
    reg [DATA_OUT_W-1:0] data_temp_r [M-1:0];

    initial begin
        for (i = 0; i < M; i = i + 1) begin
            data_temp_r[i] <= 0;
        end
    end

    always @(posedge clk) begin
        if (rst) begin
            for (i = 0; i < M; i = i + 1) begin
                data_temp_r[i] <= 0;
            end
            comb_r[k] <= 0;
        end else begin
            if (rready_i & rvalid_o) begin
                if (k == 0) begin
                    data_temp_r[0] <= $signed(int_r[N-1]);
                    comb_r[k]  <= $signed(int_r[N-1]) - $signed(data_temp_r[M-1]);
                end else begin
                    data_temp_r[0] <= $signed(comb_r[k-1]);
                    comb_r[k]  <= $signed(comb_r[k-1]) - $signed(data_temp_r[M-1]);
                end

                for (i = 0; i < M-1; i = i + 1) begin
                    data_temp_r[i+1] <= data_temp_r[i];
                end
            end
        end
    end
end
endgenerate

// Decimation counter
always @(posedge clk) begin
    if (rst) begin
        cycle_cnt <= 0;
    end else begin
        if (wready_o & wvalid_i) begin
            if (cycle_cnt < R - 1) begin
                cycle_cnt <= cycle_cnt + 1;
            end else begin
                cycle_cnt <= 0;
            end
        end
    end
end

endmodule
"""

INTERPOLATOR_TEMPLATE = """

`timescale 1ns / 1ps

module {module_name} #(
    parameter DATA_IN_W = {data_w},
    parameter R = {ratio},
    parameter M = {delay},
    parameter N = {stages},
    parameter DATA_OUT_W = {cic_int_out_expr}
)
(
    input  wire                      clk,
    input  wire                      rst,

    input  wire [DATA_IN_W-1:0]      wdata_i,
    input  wire                      wvalid_i,
    output wire                      wready_o,

    output wire [DATA_OUT_W-1:0]     rdata_o,
    output wire                      rvalid_o,
    input  wire                      rready_i
);

// Internal full-precision width
localparam FULL_OUT_W = DATA_IN_W + (N > $clog2(((R*M)**N)/R) ? N : $clog2(((R*M)**N)/R));

reg [$clog2(R+1)-1:0] cycle_cnt = 0;

// Pipeline drain counter: keeps rvalid high for R*N+N cycles after the last
// accepted input so the full latency of the comb/integrator chain drains out.
reg [$clog2(R*N+N+R+1)-1:0] drain_cnt = 0;

reg [FULL_OUT_W-1:0] comb_r[N-1:0];

reg [FULL_OUT_W-1:0] int_r[N-1:0];

assign wready_o = rready_i & (cycle_cnt == 0);

assign rdata_o = FULL_OUT_W > DATA_OUT_W ? int_r[N-1][DATA_OUT_W-1:0] : int_r[N-1];
assign rvalid_o = (wready_o & wvalid_i) | (cycle_cnt != 0) | (drain_cnt > 0);

always @(posedge clk) begin
    if (rst) begin
        drain_cnt <= 0;
    end else begin
        if (wready_o & wvalid_i) begin
            drain_cnt <= R * N + N + R + R;
        end else if (drain_cnt > 0) begin
            drain_cnt <= drain_cnt - 1;
        end
    end
end

genvar k;
integer i;

initial begin
    for (i = 0; i < N; i = i + 1) begin
        comb_r[i] <= 0;
        int_r[i] <= 0;
    end
end

// comb stages
generate

for (k = 0; k < N; k = k + 1) begin : comb
    reg [DATA_OUT_W-1:0] data_temp_r [M-1:0];

    initial begin
        for (i = 0; i < M; i = i + 1) begin
            comb_r[i] <= 0;
        end
    end

    always @(posedge clk) begin
        if (rst) begin
            for (i = 0; i < M; i = i + 1) begin
                data_temp_r[i] <= 0;
            end
            comb_r[k] <= 0;
        end else begin
            // Comb runs on every output cycle-0 tick; when no input is valid it
            // continues with zero data so the difference chain drains correctly.
            if (rready_i & rvalid_o & (cycle_cnt == 0)) begin
                if (k == 0) begin
                    data_temp_r[0] <= $signed(wvalid_i ? wdata_i : {{DATA_IN_W{{1'b0}}}});
                    comb_r[k] <= $signed(wvalid_i ? wdata_i : {{DATA_IN_W{{1'b0}}}}) - $signed(data_temp_r[M-1]);
                end else begin
                    data_temp_r[0] <= $signed(comb_r[k-1]);
                    comb_r[k] <= $signed(comb_r[k-1]) - $signed(data_temp_r[M-1]);
                end

                for (i = 0; i < M-1; i = i + 1) begin
                    data_temp_r[i+1] <= data_temp_r[i];
                end
            end
        end
    end
end

endgenerate

// integrator stages
generate

for (k = 0; k < N; k = k + 1) begin : integrator
    always @(posedge clk) begin
        if (rst) begin
            int_r[k] <= 0;
        end else begin
            if (rready_i & rvalid_o) begin
                if (k == 0) begin
                    if (cycle_cnt == 0) begin
                        int_r[k] <= $signed(int_r[k]) + $signed(comb_r[N-1]);
                    end
                end else begin
                    int_r[k] <= $signed(int_r[k]) + $signed(int_r[k-1]);
                end
            end
        end
    end
end

endgenerate

always @(posedge clk) begin
    if (rst) begin
        cycle_cnt <= 0;
    end else begin
        if (rready_i & rvalid_o) begin
            if (cycle_cnt < R - 1) begin
                cycle_cnt <= cycle_cnt + 1;
            end else begin
                cycle_cnt <= 0;
            end
        end
    end
end

endmodule
"""

FIR_P_TEMPLATE = """
// Language: Verilog 2001

`timescale 1ns / 1ps

/*
 * Parallel FIR Pre-compensation Filter
 * - Non-programmable coefficients (symmetric, linear phase)
 * - 3-stage pipeline: pre-add -> mul_riply -> accumulate
 * - Scalable to any odd TAP count via genvar/generate
 */
module {module_name} #(
    parameter DATA_IN_W  = {data_w},
    parameter TAP        = {taps},
    parameter COE_W      = {fir_width},
    parameter SCALE_W    = COE_W,
    parameter DATA_OUT_W = {fir_out_expr}
)
(
    input  wire                      clk,
    input  wire                      rst,

    /*
     * AXI stream input
     */
    input  wire [DATA_IN_W-1:0]      wdata_i,
    input  wire                      wvalid_i,
    output wire                      wready_o,

    /*
     * AXI stream output
     */
    output wire [DATA_OUT_W-1:0]     rdata_o,
    output wire                      rvalid_o,
    input  wire                      rready_i
);

// ==================== Parameters ====================
localparam HALF = (TAP + 1) / 2;  // number of unique coefficients (symmetric)
localparam FULL_W = DATA_IN_W + COE_W + $clog2(TAP);  // internal full-precision width
localparam mul_r_W = DATA_IN_W + 1 + COE_W;  // add_r is DATA_IN_W+1 bits, times COE_W

// ==================== Coefficients ====================
// Non-programmable: hardcoded symmetric coefficients
// Only the first HALF are stored; coe[k] == coe[TAP-1-k]
wire signed [COE_W-1:0] coe [0:HALF-1];

{fir_coeffs_assignments}
// ==================== Valid Pipeline ====================
// 3 stages of pipeline delay for the valid signal
// Freezes when stalled
reg [2:0] cycle_cnt;

// ==================== Pipeline Stall ====================
// Stall the entire pipeline when output is valid but downstream not ready
wire stall = cycle_cnt[2] & ~rready_i;

// ==================== Handshake ====================
wire handshake;
assign wready_o  = ~stall;  // block input when pipeline is stalled
assign handshake = wvalid_i & wready_o;

always @(posedge clk) begin
    if (rst) begin
        cycle_cnt <= 3'b000;
    end else if (!stall) begin
        cycle_cnt[0] <= handshake;
        cycle_cnt[1] <= cycle_cnt[0];
        cycle_cnt[2] <= cycle_cnt[1];
    end
end

// ==================== Shift Register (Delay Line) ====================
reg signed [DATA_IN_W-1:0] shift_r [0:TAP-1];

integer i;
always @(posedge clk) begin
    if (rst) begin
        for (i = 0; i < TAP; i = i + 1) begin
            shift_r[i] <= {{DATA_IN_W{{1'b0}}}};
        end
    end else if (!stall && handshake) begin
        shift_r[0] <= $signed(wdata_i);
        for (i = 1; i < TAP; i = i + 1) begin
            shift_r[i] <= shift_r[i-1];
        end
    end
end

// ==================== Pipeline Stage 1: Symmetric Pre-Addition ====================
// For symmetric FIR: add_r[k] = shift_r[k] + shift_r[TAP-1-k]
// Center tap (k == HALF-1 when TAP is odd): add_r = shift_r[k] only
reg signed [DATA_IN_W:0] add_r [0:HALF-1];  // DATA_IN_W+1 bits

genvar k;
generate
    for (k = 0; k < HALF; k = k + 1) begin : gen_add_r
        always @(posedge clk) begin
            if (rst) begin
                add_r[k] <= 0;
            end else if (!stall && handshake) begin
                if (k == HALF - 1 && TAP % 2 == 1) begin
                    // Center tap: no symmetric pair
                    add_r[k] <= $signed(shift_r[k]);
                end else begin
                    add_r[k] <= $signed(shift_r[k]) + $signed(shift_r[TAP-1-k]);
                end
            end
        end
    end
endgenerate

// ==================== Pipeline Stage 2: mul_riply ====================
reg signed [mul_r_W-1:0] mul_r [0:HALF-1];

generate
    for (k = 0; k < HALF; k = k + 1) begin : gen_mul_r
        always @(posedge clk) begin
            if (rst) begin
                mul_r[k] <= 0;
            end else if (!stall && cycle_cnt[0]) begin
                mul_r[k] <= add_r[k] * coe[k];
            end
        end
    end
endgenerate

// ==================== Pipeline Stage 3: Addition Tree ====================
// Combinational sum of all products, then register
reg signed [FULL_W-1:0] comb_r;

always @(*) begin
    comb_r = 0;
    for (i = 0; i < HALF; i = i + 1) begin
        comb_r = comb_r + mul_r[i];
    end
end

reg signed [FULL_W-1:0] data_temp_r;

always @(posedge clk) begin
    if (rst) begin
        data_temp_r <= 0;
    end else if (!stall && cycle_cnt[1]) begin
        data_temp_r <= comb_r;
    end
end

// ==================== Output ====================
assign rdata_o  = data_temp_r[FULL_W-1:SCALE_W];  // truncate fractional SCALE_W bits
assign rvalid_o = cycle_cnt[2];

endmodule
"""

FIR_S_TEMPLATE = """
// Language: Verilog 2001

`timescale 1ns / 1ps

/*
 * Serial FIR Pre-compensation Filter
 * - Non-programmable coefficients (symmetric, linear phase)
 * - Single multiplier, MAC-based FSM architecture
 * - Processes one tap per clock cycle (TAP cycles per sample)
 * - Scalable to any odd TAP count via genvar/generate
 */
module {module_name} #(
    parameter DATA_IN_W  = {data_w},
    parameter TAP        = {taps},
    parameter COE_W      = {fir_width},
    parameter SCALE_W    = COE_W,
    parameter DATA_OUT_W = {fir_out_expr}
)
(
    input  wire                      clk,
    input  wire                      rst,

    /*
     * AXI stream input
     */
    input  wire [DATA_IN_W-1:0]      wdata_i,
    input  wire                      wvalid_i,
    output wire                      wready_o,

    /*
     * AXI stream output
     */
    output wire [DATA_OUT_W-1:0]     rdata_o,
    output wire                      rvalid_o,
    input  wire                      rready_i
);

// ==================== Parameters ====================
localparam CNT_W = $clog2(TAP);  // counter width
localparam FULL_W = DATA_IN_W + COE_W + $clog2(TAP);  // internal full-precision width
localparam MULT_W = DATA_IN_W + COE_W;  // multiplier output width

// FSM states
localparam S_IDLE = 2'd0;
localparam S_CALC = 2'd1;
localparam S_DONE = 2'd2;

// ==================== Coefficients ====================
// Full TAP coefficients (symmetric expansion)
wire signed [COE_W-1:0] coe [0:TAP-1];

{fir_coeffs_assignments}
// ==================== FSM ====================
reg [1:0] state_r, state_next;
reg [CNT_W-1:0] cycle_cnt;

always @(posedge clk) begin
    if (rst) begin
        state_r <= S_IDLE;
    end else begin
        state_r <= state_next;
    end
end

always @(*) begin
    case (state_r)
        S_IDLE: begin
            if (wvalid_i)
                state_next = S_CALC;
            else
                state_next = S_IDLE;
        end
        S_CALC: begin
            if (cycle_cnt == TAP - 1)
                state_next = S_DONE;
            else
                state_next = S_CALC;
        end
        S_DONE: begin
            if (rready_i)
                state_next = S_IDLE;
            else
                state_next = S_DONE;
        end
        default: state_next = S_IDLE;
    endcase
end

// ==================== Handshake ====================
assign wready_o = (state_r == S_IDLE);
assign rvalid_o = (state_r == S_DONE);

// ==================== Tap Counter ====================
always @(posedge clk) begin
    if (rst) begin
        cycle_cnt <= 0;
    end else begin
        if (state_r == S_CALC)
            cycle_cnt <= cycle_cnt + 1;
        else
            cycle_cnt <= 0;
    end
end

// ==================== Shift Register (Delay Line) ====================
reg signed [DATA_IN_W-1:0] shift_r [0:TAP-1];

integer i;
always @(posedge clk) begin
    if (rst) begin
        for (i = 0; i < TAP; i = i + 1) begin
            shift_r[i] <= 0;
        end
    end else if (state_r == S_IDLE && wvalid_i) begin
        // Load new sample and shift
        shift_r[0] <= $signed(wdata_i);
        for (i = 1; i < TAP; i = i + 1) begin
            shift_r[i] <= shift_r[i-1];
        end
    end
end

// ==================== MAC: Multiply-Accumulate ====================
wire signed [MULT_W-1:0] mul_r;
assign mul_r = $signed(shift_r[cycle_cnt]) * $signed(coe[cycle_cnt]);

reg signed [FULL_W-1:0] acc_r;

always @(posedge clk) begin
    if (rst) begin
        acc_r <= 0;
    end else begin
        if (state_r == S_IDLE && wvalid_i) begin
            // Reset accumulator when loading new sample
            acc_r <= 0;
        end else if (state_r == S_CALC) begin
            acc_r <= acc_r + mul_r;
        end
    end
end

// ==================== Output ====================
assign rdata_o = acc_r[FULL_W-1:SCALE_W];  // truncate fractional SCALE_W bits

endmodule
"""

FIR_M_TEMPLATE = """
// Language: Verilog 2001

`timescale 1ns / 1ps

/*
 * Distributed Arithmetic FIR Pre-compensation Filter
 * - Non-programmable coefficients (symmetric, linear phase)
 * - Multiplier-free: uses LUT-based distributed arithmetic
 * - Segmented DA: splits TAP taps into groups (max 8 per group)
 * - Processes from LSB to MSB, one bit per clock (DATA_IN_W cycles per sample)
 * - Scalable to any odd TAP count via genvar/generate
 *
 * DA Principle:
 *   y = sum_k {{ h[k] * x[k] }}
 *     = sum_k {{ h[k] * sum_j {{ x[k][j] * 2^j }} }}   (x[k][j] is bit j of x[k])
 *     = sum_j {{ 2^j * sum_k {{ h[k] * x[k][j] }} }}
 *     = sum_j {{ 2^j * LUT( x[0][j], x[1][j], ..., x[TAP-1][j] ) }}
 *
 *   Process from j=0 (LSB) to j=DATA_IN_W-1 (MSB/sign):
 *     acc = 0
 *     for j = 0 to DATA_IN_W-2:    acc = (acc >> 1) + (LUT_val << (DATA_IN_W-1))
 *     for j = DATA_IN_W-1 (sign):   acc = (acc >> 1) - (LUT_val << (DATA_IN_W-1))
 *
 *   After DATA_IN_W iterations, acc holds the final result.
 */
module {module_name} #(
    parameter DATA_IN_W  = {data_w},
    parameter TAP        = {taps},
    parameter COE_W      = {fir_width},
    parameter SCALE_W    = COE_W,
    parameter DATA_OUT_W = {fir_out_expr}
)
(
    input  wire                      clk,
    input  wire                      rst,

    /*
     * AXI stream input
     */
    input  wire [DATA_IN_W-1:0]      wdata_i,
    input  wire                      wvalid_i,
    output wire                      wready_o,

    /*
     * AXI stream output
     */
    output wire [DATA_OUT_W-1:0]     rdata_o,
    output wire                      rvalid_o,
    input  wire                      rready_i
);

// ==================== Parameters ====================
localparam BIT_CNT_W = $clog2(DATA_IN_W + 1);
localparam FULL_W = DATA_IN_W + COE_W + $clog2(TAP);  // internal full-precision width
// LUT entry width: sum of up to 8 coefficients, need enough bits
localparam LUT_DATA_W = COE_W + 4;  // COE_W + log2(max_group_size=8) = COE_W+3, +1 for safety

// Group sizes for segmented DA
localparam G0_SIZE = 8;                       // Group 0: taps 0..7
localparam G1_SIZE = TAP - G0_SIZE;           // Group 1: taps 8..14 (=7)

// FSM states
localparam S_IDLE = 2'd0;
localparam S_CALC = 2'd1;
localparam S_DONE = 2'd2;

// ==================== Coefficients ====================
wire signed [COE_W-1:0] coe [0:TAP-1];

{fir_coeffs_assignments}
// ==================== FSM ====================
reg [1:0] state_r, state_next;
reg [BIT_CNT_W-1:0] cycle_cnt;

always @(posedge clk) begin
    if (rst)
        state_r <= S_IDLE;
    else
        state_r <= state_next;
end

always @(*) begin
    case (state_r)
        S_IDLE:   state_next = (wvalid_i) ? S_CALC : S_IDLE;
        S_CALC:   state_next = (cycle_cnt == DATA_IN_W - 1) ? S_DONE : S_CALC;
        S_DONE:   state_next = (rready_i) ? S_IDLE : S_DONE;
        default:  state_next = S_IDLE;
    endcase
end

// ==================== Handshake ====================
assign wready_o = (state_r == S_IDLE);
assign rvalid_o = (state_r == S_DONE);

// ==================== Bit Counter ====================
always @(posedge clk) begin
    if (rst)
        cycle_cnt <= 0;
    else if (state_r == S_CALC)
        cycle_cnt <= cycle_cnt + 1;
    else
        cycle_cnt <= 0;
end

// ==================== Shift Register (Delay Line) ====================
reg signed [DATA_IN_W-1:0] shift_r [0:TAP-1];

integer i;
always @(posedge clk) begin
    if (rst) begin
        for (i = 0; i < TAP; i = i + 1)
            shift_r[i] <= 0;
    end else if (state_r == S_IDLE && wvalid_i) begin
        shift_r[0] <= $signed(wdata_i);
        for (i = 1; i < TAP; i = i + 1)
            shift_r[i] <= shift_r[i-1];
    end
end

// ==================== LUT Tables ====================
// Group 0 LUT: 2^8 = 256 entries (taps 0..7)
reg signed [LUT_DATA_W-1:0] lut_g0 [0:255];
// Group 1 LUT: 2^7 = 128 entries (taps 8..14)
reg signed [LUT_DATA_W-1:0] lut_g1 [0:127];

integer j, m;
initial begin
    for (j = 0; j < 256; j = j + 1) begin
        lut_g0[j] = 0;
        for (m = 0; m < G0_SIZE; m = m + 1) begin
            if (j[m])
                lut_g0[j] = lut_g0[j] + coe[m];
        end
    end
    for (j = 0; j < 128; j = j + 1) begin
        lut_g1[j] = 0;
        for (m = 0; m < G1_SIZE; m = m + 1) begin
            if (j[m])
                lut_g1[j] = lut_g1[j] + coe[G0_SIZE + m];
        end
    end
end

// ==================== Bit Extraction & LUT Addressing ====================
wire [G0_SIZE-1:0] lut_addr_0;
wire [G1_SIZE-1:0] lut_addr_1;

genvar k;
generate
    for (k = 0; k < G0_SIZE; k = k + 1) begin : gen_addr0
        assign lut_addr_0[k] = shift_r[k][cycle_cnt];
    end
    for (k = 0; k < G1_SIZE; k = k + 1) begin : gen_addr1
        assign lut_addr_1[k] = shift_r[G0_SIZE + k][cycle_cnt];
    end
endgenerate

// Combined LUT output
wire signed [LUT_DATA_W:0] lut_sum;
assign lut_sum = $signed(lut_g0[lut_addr_0]) + $signed(lut_g1[lut_addr_1]);

// ==================== DA Shift-Accumulate ====================
// Process from LSB (bit 0) to MSB (bit DATA_IN_W-1)
// For bits 0..DATA_IN_W-2: acc = (acc >>> 1) + (lut_sum <<< shift_amount)
// For bit DATA_IN_W-1 (sign): acc = (acc >>> 1) - (lut_sum <<< shift_amount)
//
// shift_amount positions the LUT value correctly:
// After DATA_IN_W iterations with arithmetic right shift, bit 0's contribution
// will have been shifted right DATA_IN_W-1 times → effectively × 2^0.
// We place lut_sum at the MSB region, so shift_amount = DATA_OUT_W - 1 - (LUT_DATA_W).
// But simpler: accumulate in a wider register, final result = acc >>> extra_bits.

// Simplified approach: use standard DA accumulation
// acc starts at 0
// Each cycle: acc = (acc >>> 1), then add/subtract lut_sum shifted to MSB position
localparam SHIFT_POS = FULL_W - 1;

reg signed [FULL_W-1:0] acc_r;

always @(posedge clk) begin
    if (rst) begin
        acc_r <= 0;
    end else if (state_r == S_IDLE && wvalid_i) begin
        acc_r <= 0;
    end else if (state_r == S_CALC) begin
        if (cycle_cnt == DATA_IN_W - 1) begin
            // Sign bit: subtract
            acc_r <= (acc_r >>> 1) - (lut_sum <<< (SHIFT_POS - LUT_DATA_W));
        end else begin
            // Regular bit: add
            acc_r <= (acc_r >>> 1) + (lut_sum <<< (SHIFT_POS - LUT_DATA_W));
        end
    end
end

// ==================== Output ====================
assign rdata_o = acc_r[FULL_W-1:SCALE_W];  // truncate fractional SCALE_W bits

endmodule
"""

CIC_DEC_FIR_P_TOP_TEMPLATE = """
// Language: Verilog 2001

`timescale 1ns / 1ps

/*
 * Top-level: CIC Decimator + Parallel FIR Compensation
 * Signal chain: in -> cic_dec -> fir_p -> out
 */
module {module_name} #(
    parameter DATA_IN_W  = {data_w},
    parameter TAP        = {taps},
    parameter COE_W      = {fir_width},
    parameter R          = {ratio},
    parameter M          = {delay},
    parameter N          = {stages},
    parameter CIC_OUT_W  = DATA_IN_W + $clog2((R*M)**N),
    parameter DATA_OUT_W = {cic_fir_out_expr}
)
(
    input  wire                      clk,
    input  wire                      rst,

    input  wire [DATA_IN_W-1:0]      wdata_i,
    input  wire                      wvalid_i,
    output wire                      wready_o,

    output wire [DATA_OUT_W-1:0]     rdata_o,
    output wire                      rvalid_o,
    input  wire                      rready_i
);

// ==================== Internal Wires ====================
wire [CIC_OUT_W-1:0] cic2fir_data;
wire                  cic2fir_valid;
wire                  cic2fir_ready;

// ==================== CIC Decimator ====================
{cic_module_name} #(
    .DATA_IN_W  (DATA_IN_W),
    .R          (R),
    .M          (M),
    .N          (N)
) u_cic (
    .clk        (clk),
    .rst        (rst),
    .wdata_i    (wdata_i),
    .wvalid_i   (wvalid_i),
    .wready_o   (wready_o),
    .rdata_o    (cic2fir_data),
    .rvalid_o   (cic2fir_valid),
    .rready_i   (cic2fir_ready)
);

localparam FILTER_FULL_W = CIC_OUT_W + $clog2(TAP);
wire [FILTER_FULL_W-1:0] filter_out_full;

// ==================== FIR (Parallel) ====================
{fir_module_name} #(
    .DATA_IN_W  (CIC_OUT_W),
    .TAP        (TAP),
    .COE_W      (COE_W),
    .SCALE_W    ({fir_scale_w})
) u_fir (
    .clk        (clk),
    .rst        (rst),
    .wdata_i    (cic2fir_data),
    .wvalid_i   (cic2fir_valid),
    .wready_o   (cic2fir_ready),
    .rdata_o    (filter_out_full),
    .rvalid_o   (rvalid_o),
    .rready_i   (rready_i)
);

// ==================== Output Truncation ====================
generate
    if (FILTER_FULL_W > DATA_OUT_W) begin : gen_trunc
        assign rdata_o = filter_out_full[DATA_OUT_W-1:0];
    end else begin : gen_full
        assign rdata_o = filter_out_full;
    end
endgenerate

endmodule
"""

CIC_DEC_FIR_S_TOP_TEMPLATE = """
// Language: Verilog 2001

`timescale 1ns / 1ps

/*
 * Top-level: CIC Decimator + Serial FIR Compensation
 * Signal chain: in -> cic_dec -> fir_s -> out
 */
module {module_name} #(
    parameter DATA_IN_W  = {data_w},
    parameter TAP        = {taps},
    parameter COE_W      = {fir_width},
    parameter R          = {ratio},
    parameter M          = {delay},
    parameter N          = {stages},
    parameter CIC_OUT_W  = DATA_IN_W + $clog2((R*M)**N),
    parameter DATA_OUT_W = {cic_fir_out_expr}
)
(
    input  wire                      clk,
    input  wire                      rst,

    input  wire [DATA_IN_W-1:0]      wdata_i,
    input  wire                      wvalid_i,
    output wire                      wready_o,

    output wire [DATA_OUT_W-1:0]     rdata_o,
    output wire                      rvalid_o,
    input  wire                      rready_i
);

// ==================== Internal Wires ====================
wire [CIC_OUT_W-1:0] cic2fir_data;
wire                  cic2fir_valid;
wire                  cic2fir_ready;

// ==================== CIC Decimator ====================
{cic_module_name} #(
    .DATA_IN_W  (DATA_IN_W),
    .R          (R),
    .M          (M),
    .N          (N)
) u_cic (
    .clk        (clk),
    .rst        (rst),
    .wdata_i    (wdata_i),
    .wvalid_i   (wvalid_i),
    .wready_o   (wready_o),
    .rdata_o    (cic2fir_data),
    .rvalid_o   (cic2fir_valid),
    .rready_i   (cic2fir_ready)
);

localparam FILTER_FULL_W = CIC_OUT_W + $clog2(TAP);
wire [FILTER_FULL_W-1:0] filter_out_full;

// ==================== FIR (Serial) ====================
{fir_module_name} #(
    .DATA_IN_W  (CIC_OUT_W),
    .TAP        (TAP),
    .COE_W      (COE_W),
    .SCALE_W    ({fir_scale_w})
) u_fir (
    .clk        (clk),
    .rst        (rst),
    .wdata_i    (cic2fir_data),
    .wvalid_i   (cic2fir_valid),
    .wready_o   (cic2fir_ready),
    .rdata_o    (filter_out_full),
    .rvalid_o   (rvalid_o),
    .rready_i   (rready_i)
);

// ==================== Output Truncation ====================
generate
    if (FILTER_FULL_W > DATA_OUT_W) begin : gen_trunc
        assign rdata_o = filter_out_full[DATA_OUT_W-1:0];
    end else begin : gen_full
        assign rdata_o = filter_out_full;
    end
endgenerate

endmodule
"""

CIC_DEC_FIR_M_TOP_TEMPLATE = """
// Language: Verilog 2001

`timescale 1ns / 1ps

/*
 * Top-level: CIC Decimator + Distributed Arithmetic FIR Compensation
 * Signal chain: in -> cic_dec -> fir_m -> out
 */
module {module_name} #(
    parameter DATA_IN_W  = {data_w},
    parameter TAP        = {taps},
    parameter COE_W      = {fir_width},
    parameter R          = {ratio},
    parameter M          = {delay},
    parameter N          = {stages},
    parameter CIC_OUT_W  = DATA_IN_W + $clog2((R*M)**N),
    parameter DATA_OUT_W = {cic_fir_out_expr}
)
(
    input  wire                      clk,
    input  wire                      rst,

    input  wire [DATA_IN_W-1:0]      wdata_i,
    input  wire                      wvalid_i,
    output wire                      wready_o,

    output wire [DATA_OUT_W-1:0]     rdata_o,
    output wire                      rvalid_o,
    input  wire                      rready_i
);

// ==================== Internal Wires ====================
wire [CIC_OUT_W-1:0] cic2fir_data;
wire                  cic2fir_valid;
wire                  cic2fir_ready;

// ==================== CIC Decimator ====================
{cic_module_name} #(
    .DATA_IN_W  (DATA_IN_W),
    .R          (R),
    .M          (M),
    .N          (N)
) u_cic (
    .clk        (clk),
    .rst        (rst),
    .wdata_i    (wdata_i),
    .wvalid_i   (wvalid_i),
    .wready_o   (wready_o),
    .rdata_o    (cic2fir_data),
    .rvalid_o   (cic2fir_valid),
    .rready_i   (cic2fir_ready)
);

localparam FILTER_FULL_W = CIC_OUT_W + $clog2(TAP);
wire [FILTER_FULL_W-1:0] filter_out_full;

// ==================== FIR (Distributed Arithmetic) ====================
{fir_module_name} #(
    .DATA_IN_W  (CIC_OUT_W),
    .TAP        (TAP),
    .COE_W      (COE_W),
    .SCALE_W    ({fir_scale_w})
) u_fir (
    .clk        (clk),
    .rst        (rst),
    .wdata_i    (cic2fir_data),
    .wvalid_i   (cic2fir_valid),
    .wready_o   (cic2fir_ready),
    .rdata_o    (filter_out_full),
    .rvalid_o   (rvalid_o),
    .rready_i   (rready_i)
);

// ==================== Output Truncation ====================
generate
    if (FILTER_FULL_W > DATA_OUT_W) begin : gen_trunc
        assign rdata_o = filter_out_full[DATA_OUT_W-1:0];
    end else begin : gen_full
        assign rdata_o = filter_out_full;
    end
endgenerate

endmodule
"""

FIR_P_CIC_INT_TOP_TEMPLATE = """
// Language: Verilog 2001

`timescale 1ns / 1ps

/*
 * Top-level: Parallel FIR Pre-compensation + CIC Interpolator
 * Signal chain: in -> fir_p -> cic_int -> out
 * fir_p supports backpressure via pipeline stall, so direct connection works.
 */
module {module_name} #(
    parameter DATA_IN_W  = {data_w},
    parameter TAP        = {taps},
    parameter COE_W      = {fir_width},
    parameter R          = {ratio},
    parameter M          = {delay},
    parameter N          = {stages},
    parameter FIR_OUT_W  = DATA_IN_W + $clog2(TAP),
    parameter DATA_OUT_W = {fir_cic_out_expr}
)
(
    input  wire                      clk,
    input  wire                      rst,

    input  wire [DATA_IN_W-1:0]      wdata_i,
    input  wire                      wvalid_i,
    output wire                      wready_o,

    output wire [DATA_OUT_W-1:0]     rdata_o,
    output wire                      rvalid_o,
    input  wire                      rready_i
);

// ==================== Internal Wires ====================
wire [FIR_OUT_W-1:0] fir2cic_data;
wire                 fir2cic_valid;
wire                 fir2cic_ready;
localparam FILTER_FULL_W = FIR_OUT_W + (N > $clog2(((R*M)**N)/R) ? N : $clog2(((R*M)**N)/R));
wire [FILTER_FULL_W-1:0] filter_out_full;

// ==================== FIR (Parallel) ====================
{fir_module_name} #(
    .DATA_IN_W  (DATA_IN_W),
    .TAP        (TAP),
    .COE_W      (COE_W),
    .SCALE_W    ({fir_scale_w})
) u_fir (
    .clk        (clk),
    .rst        (rst),
    .wdata_i    (wdata_i),
    .wvalid_i   (wvalid_i),
    .wready_o   (wready_o),
    .rdata_o    (fir2cic_data),
    .rvalid_o   (fir2cic_valid),
    .rready_i   (fir2cic_ready)
);

// ==================== CIC Interpolator ====================
{cic_module_name} #(
    .DATA_IN_W  (FIR_OUT_W),
    .R          (R),
    .M          (M),
    .N          (N)
) u_cic (
    .clk        (clk),
    .rst        (rst),
    .wdata_i    (fir2cic_data),
    .wvalid_i   (fir2cic_valid),
    .wready_o   (fir2cic_ready),
    .rdata_o    (filter_out_full),
    .rvalid_o   (rvalid_o),
    .rready_i   (rready_i)
);

// ==================== Output Truncation ====================
generate
    if (FILTER_FULL_W > DATA_OUT_W) begin : gen_trunc
        assign rdata_o = filter_out_full[DATA_OUT_W-1:0];
    end else begin : gen_full
        assign rdata_o = filter_out_full;
    end
endgenerate

endmodule
"""

FIR_S_CIC_INT_TOP_TEMPLATE = """
// Language: Verilog 2001

`timescale 1ns / 1ps

/*
 * Top-level: Serial FIR Pre-compensation + CIC Interpolator
 * Signal chain: in -> fir_s -> cic_int -> out
 * fir_s uses FSM with held rvalid_o, naturally supports backpressure.
 */
module {module_name} #(
    parameter DATA_IN_W  = {data_w},
    parameter TAP        = {taps},
    parameter COE_W      = {fir_width},
    parameter R          = {ratio},
    parameter M          = {delay},
    parameter N          = {stages},
    parameter FIR_OUT_W  = DATA_IN_W + $clog2(TAP),
    parameter DATA_OUT_W = {fir_cic_out_expr}
)
(
    input  wire                      clk,
    input  wire                      rst,

    input  wire [DATA_IN_W-1:0]      wdata_i,
    input  wire                      wvalid_i,
    output wire                      wready_o,

    output wire [DATA_OUT_W-1:0]     rdata_o,
    output wire                      rvalid_o,
    input  wire                      rready_i
);

// ==================== Internal Wires ====================
wire [FIR_OUT_W-1:0] fir2cic_data;
wire                 fir2cic_valid;
wire                 fir2cic_ready;
localparam FILTER_FULL_W = FIR_OUT_W + (N > $clog2(((R*M)**N)/R) ? N : $clog2(((R*M)**N)/R));
wire [FILTER_FULL_W-1:0] filter_out_full;

// ==================== FIR (Serial) ====================
{fir_module_name} #(
    .DATA_IN_W  (DATA_IN_W),
    .TAP        (TAP),
    .COE_W      (COE_W),
    .SCALE_W    ({fir_scale_w})
) u_fir (
    .clk        (clk),
    .rst        (rst),
    .wdata_i    (wdata_i),
    .wvalid_i   (wvalid_i),
    .wready_o   (wready_o),
    .rdata_o    (fir2cic_data),
    .rvalid_o   (fir2cic_valid),
    .rready_i   (fir2cic_ready)
);

// ==================== CIC Interpolator ====================
{cic_module_name} #(
    .DATA_IN_W  (FIR_OUT_W),
    .R          (R),
    .M          (M),
    .N          (N)
) u_cic (
    .clk        (clk),
    .rst        (rst),
    .wdata_i    (fir2cic_data),
    .wvalid_i   (fir2cic_valid),
    .wready_o   (fir2cic_ready),
    .rdata_o    (filter_out_full),
    .rvalid_o   (rvalid_o),
    .rready_i   (rready_i)
);

// ==================== Output Truncation ====================
generate
    if (FILTER_FULL_W > DATA_OUT_W) begin : gen_trunc
        assign rdata_o = filter_out_full[DATA_OUT_W-1:0];
    end else begin : gen_full
        assign rdata_o = filter_out_full;
    end
endgenerate

endmodule
"""

FIR_M_CIC_INT_TOP_TEMPLATE = """
// Language: Verilog 2001

`timescale 1ns / 1ps

/*
 * Top-level: Distributed Arithmetic FIR Pre-compensation + CIC Interpolator
 * Signal chain: in -> fir_m -> cic_int -> out
 * fir_m uses FSM with held rvalid_o, naturally supports backpressure.
 */
module {module_name} #(
    parameter DATA_IN_W  = {data_w},
    parameter TAP        = {taps},
    parameter COE_W      = {fir_width},
    parameter R          = {ratio},
    parameter M          = {delay},
    parameter N          = {stages},
    parameter FIR_OUT_W  = DATA_IN_W + $clog2(TAP),
    parameter DATA_OUT_W = {fir_cic_out_expr}
)
(
    input  wire                      clk,
    input  wire                      rst,

    input  wire [DATA_IN_W-1:0]      wdata_i,
    input  wire                      wvalid_i,
    output wire                      wready_o,

    output wire [DATA_OUT_W-1:0]     rdata_o,
    output wire                      rvalid_o,
    input  wire                      rready_i
);

// ==================== Internal Wires ====================
wire [FIR_OUT_W-1:0] fir2cic_data;
wire                 fir2cic_valid;
wire                 fir2cic_ready;
localparam FILTER_FULL_W = FIR_OUT_W + (N > $clog2(((R*M)**N)/R) ? N : $clog2(((R*M)**N)/R));
wire [FILTER_FULL_W-1:0] filter_out_full;

// ==================== FIR (Distributed Arithmetic) ====================
{fir_module_name} #(
    .DATA_IN_W  (DATA_IN_W),
    .TAP        (TAP),
    .COE_W      (COE_W),
    .SCALE_W    ({fir_scale_w})
) u_fir (
    .clk        (clk),
    .rst        (rst),
    .wdata_i    (wdata_i),
    .wvalid_i   (wvalid_i),
    .wready_o   (wready_o),
    .rdata_o    (fir2cic_data),
    .rvalid_o   (fir2cic_valid),
    .rready_i   (fir2cic_ready)
);

// ==================== CIC Interpolator ====================
{cic_module_name} #(
    .DATA_IN_W  (FIR_OUT_W),
    .R          (R),
    .M          (M),
    .N          (N)
) u_cic (
    .clk        (clk),
    .rst        (rst),
    .wdata_i    (fir2cic_data),
    .wvalid_i   (fir2cic_valid),
    .wready_o   (fir2cic_ready),
    .rdata_o    (filter_out_full),
    .rvalid_o   (rvalid_o),
    .rready_i   (rready_i)
);

// ==================== Output Truncation ====================
generate
    if (FILTER_FULL_W > DATA_OUT_W) begin : gen_trunc
        assign rdata_o = filter_out_full[DATA_OUT_W-1:0];
    end else begin : gen_full
        assign rdata_o = filter_out_full;
    end
endgenerate

endmodule
"""

DECIMATOR_TB_TEMPLATE = """`timescale 1ns / 1ps

module {module_name}_tb;

    parameter WIDTH = {data_w};
    parameter RMAX  = {ratio};
    parameter M     = {delay};
    parameter N     = {stages};
    parameter REG_WIDTH = WIDTH + N * ((RMAX*M > 1) ? $clog2(RMAX*M) : 1);
    parameter CLK_PERIOD = 10;

    reg clk, {reset_signal};
    reg [WIDTH-1:0] tdata_i;
    reg tvalid_i;
    wire tready_o;
    wire [REG_WIDTH-1:0] rdata_o;
    wire rvalid_o;
    reg rready_i;
    reg [$clog2(RMAX+1)-1:0] rate;

    {module_name} #(.WIDTH(WIDTH), .RMAX(RMAX), .M(M), .N(N)) dut (
        .clk(clk), .{reset_signal}({reset_signal}),
        .tdata_i(tdata_i), .tvalid_i(tvalid_i), .tready_o(tready_o),
        .rdata_o(rdata_o), .rvalid_o(rvalid_o), .rready_i(rready_i),
        .rate(rate)
    );

    initial begin clk = 0; forever #(CLK_PERIOD/2) clk = ~clk; end

    integer i, out_cnt;
    initial begin
        {reset_signal} = {reset_active}; tdata_i = 0; tvalid_i = 0; rready_i = 1; rate = RMAX; out_cnt = 0;
        #(CLK_PERIOD*10); {reset_signal} = {reset_inactive}; #(CLK_PERIOD*5);
        
        @(posedge clk); tdata_i = 1000; tvalid_i = 1;
        @(posedge clk); tvalid_i = 0;
        for (i = 0; i < RMAX*20; i = i + 1) begin @(posedge clk); tvalid_i = 1; tdata_i = 0; end
        
        #(CLK_PERIOD*50); $display("Done. Outputs: %d", out_cnt); $finish;
    end

    always @(posedge clk) if (rvalid_o && rready_i) begin
        out_cnt = out_cnt + 1;
        $display("Out[%d] = %d", out_cnt, $signed(rdata_o));
    end

    initial begin $dumpfile("{module_name}_tb.vcd"); $dumpvars(0, {module_name}_tb); end

endmodule
"""

INTERPOLATOR_TB_TEMPLATE = """`timescale 1ns / 1ps

module {module_name}_tb;

    parameter WIDTH = {data_w};
    parameter RMAX  = {ratio};
    parameter M     = {delay};
    parameter N     = {stages};
    parameter REG_WIDTH = WIDTH + ((N > 0) ? N : 1) * ((RMAX*M > 1) ? $clog2(RMAX*M) : 1);
    parameter CLK_PERIOD = 10;

    reg clk, {reset_signal};
    reg [WIDTH-1:0] tdata_i;
    reg tvalid_i;
    wire tready_o;
    wire [REG_WIDTH-1:0] rdata_o;
    wire rvalid_o;
    reg rready_i;
    reg [$clog2(RMAX+1)-1:0] rate;

    {module_name} #(.WIDTH(WIDTH), .RMAX(RMAX), .M(M), .N(N)) dut (
        .clk(clk), .{reset_signal}({reset_signal}),
        .tdata_i(tdata_i), .tvalid_i(tvalid_i), .tready_o(tready_o),
        .rdata_o(rdata_o), .rvalid_o(rvalid_o), .rready_i(rready_i),
        .rate(rate)
    );

    initial begin clk = 0; forever #(CLK_PERIOD/2) clk = ~clk; end

    integer i, in_cnt, out_cnt;
    initial begin
        {reset_signal} = {reset_active}; tdata_i = 0; tvalid_i = 0; rready_i = 1; rate = RMAX;
        in_cnt = 0; out_cnt = 0;
        #(CLK_PERIOD*10); {reset_signal} = {reset_inactive}; #(CLK_PERIOD*5);
        
        for (i = 0; i < 20; i = i + 1) begin
            wait(tready_o); @(posedge clk);
            tdata_i = 1000; tvalid_i = 1;
            @(posedge clk); tvalid_i = 0;
            #(CLK_PERIOD * RMAX);
        end
        
        #(CLK_PERIOD*RMAX*5); $display("In: %d, Out: %d", in_cnt, out_cnt); $finish;
    end

    always @(posedge clk) begin
        if (tvalid_i && tready_o) in_cnt = in_cnt + 1;
        if (rvalid_o && rready_i) begin
            out_cnt = out_cnt + 1;
            if (out_cnt <= 30) $display("Out[%d] = %d", out_cnt, $signed(rdata_o));
        end
    end

    initial begin $dumpfile("{module_name}_tb.vcd"); $dumpvars(0, {module_name}_tb); end

endmodule
"""

