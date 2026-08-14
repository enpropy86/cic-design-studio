
import numpy as np
import math
from functools import lru_cache
from scipy import signal

def to_verilog_signed(val, width):
    if val < 0:
        return f"-{width}'sd{abs(val)}"
    else:
        return f"{width}'sd{val}"

def calc_cic_growth(N, M, R, is_interpolator=False):
    """
    Calculate CIC filter bit growth.

    N: number of stages
    M: differential delay
    R: decimation/interpolation ratio
    is_interpolator: use interpolator formula (accounts for zero-stuffing)

    Returns integer bit growth.
    """
    if is_interpolator:
        return max(N, int(math.ceil(math.log2(((R * M) ** N) / R))))
    else:
        return N * int(math.ceil(math.log2(R * M)))


def get_cic_response_raw(freqs_norm, R, N, M=1):
    """Return CIC magnitude with DC normalized to 1."""
    freqs_norm = np.asarray(freqs_norm, dtype=float)
    with np.errstate(divide='ignore', invalid='ignore'):
        num = np.sin(np.pi * R * M * freqs_norm)
        den = R * M * np.sin(np.pi * freqs_norm)
        den_safe = np.where(np.abs(den) < 1e-12, 1e-12, den)
        H = np.abs(num / den_safe) ** N

    if H.ndim == 0:
        return 1.0 if abs(float(freqs_norm)) < 1e-12 else float(H)
    H[np.abs(freqs_norm) < 1e-12] = 1.0
    return H

def _build_compensation_target(N, R, M, num_points=257, passband_ratio=1.0):
    """Build the CIC compensation target on the FIR's own Nyquist axis [0,1].

    The inverse-CIC target is only applied inside the useful passband
    (passband_ratio of the axis). Beyond the passband the target rolls off to
    zero so the FIR does not cancel the CIC rolloff (which would otherwise
    destroy alias/image rejection at the band edge).
    """
    fir_freqs = np.linspace(0, 1.0, num_points)
    freqs_for_cic = fir_freqs / (2.0 * R)
    H_cic = get_cic_response_raw(freqs_for_cic, R, N, M)
    H_target = 1.0 / np.maximum(H_cic, 1e-12)
    if passband_ratio is not None and passband_ratio < 1.0:
        pb_ratio = max(0.1, min(0.99, float(passband_ratio)))
        pb_idx = int(round(pb_ratio * (num_points - 1)))
        # smooth transition band so firls does not ring at the hard cutoff
        trans = max(2, int(0.08 * num_points))
        end = min(num_points - 1, pb_idx + trans)
        H_target[pb_idx:end + 1] = np.linspace(H_target[pb_idx], 0.0, end - pb_idx + 1)
        if end + 1 < num_points:
            H_target[end + 1:] = 0.0
    return fir_freqs, H_target


def get_useful_band_edge(mode, R):
    mode_l = (mode or '').lower()
    return 1.0 / R if 'interpolator' in mode_l else 1.0


def _firls_from_target(taps, fir_freqs, H_target):
    bands = np.empty((len(fir_freqs) - 1) * 2, dtype=float)
    desired = np.empty_like(bands)
    bands[0::2] = fir_freqs[:-1]
    bands[1::2] = fir_freqs[1:]
    desired[0::2] = H_target[:-1]
    desired[1::2] = H_target[1:]
    return signal.firls(taps, bands, desired, fs=2.0)


@lru_cache(maxsize=128)
def _cached_fir_design(N, R, M, taps, coeff_width, window_type, antisymmetric, response_mode, passband_ratio):
    fir_freqs, H_target = _build_compensation_target(N, R, M, passband_ratio=passband_ratio)

    if antisymmetric:
        tgt = H_target.copy()
        # Type III antisymmetric FIR must have zero gain at DC and Nyquist;
        # smooth the target to zero there so firwin2 accepts it
        ramp = min(12, max(3, len(tgt) // 16))
        tgt[:ramp] = H_target[:ramp] * np.linspace(0.0, 1.0, ramp)
        tgt[-ramp:] = H_target[-ramp:] * np.linspace(1.0, 0.0, ramp)
        coeffs_float = signal.firwin2(
            taps,
            fir_freqs,
            tgt,
            window=window_type,
            antisymmetric=True
        )
    else:
        coeffs_float = _firls_from_target(taps, fir_freqs, H_target)

    max_val = np.max(np.abs(coeffs_float))
    max_possible_int = 2**(coeff_width - 1) - 1

    if max_val == 0:
        best_shift = 0
    else:
        best_shift = int(math.floor(math.log2(max_possible_int / max_val)))

    coeffs_int = tuple(int(round(c * (2**best_shift))) for c in coeffs_float)
    verilog_coeffs_list = tuple(to_verilog_signed(c, coeff_width) for c in coeffs_int)
    return best_shift, verilog_coeffs_list


def calculate_fir_params(N, R, M, taps, passband_ratio, coeff_width,
                         window_type='hamming', antisymmetric=False,
                         response_mode='decimator'):
    """Design a CIC compensation FIR.

    passband_ratio limits the compensation to the useful band (fraction of the
    FIR Nyquist axis); beyond it the target rolls off to zero so the CIC's own
    alias/image rejection at the band edge is preserved.
    """
    if taps % 2 == 0:
        raise ValueError(f"FIR Taps ({taps}) must be an odd number.")
    response_mode_l = (response_mode or 'decimator').lower()
    if response_mode_l not in ('decimator', 'interpolator'):
        raise ValueError(f"Unsupported response_mode: {response_mode}")

    best_shift, verilog_coeffs_list = _cached_fir_design(
        int(N), int(R), int(M), int(taps), int(coeff_width),
        str(window_type), bool(antisymmetric), response_mode_l,
        float(passband_ratio) if passband_ratio is not None else 1.0
    )
    return best_shift, list(verilog_coeffs_list)

def analyze_response_wide(N, R, M=1, taps=15, passband_ratio=0.5, coeff_width=16,
                          window_type='hamming', antisymmetric=False,
                          mode='Decimator'):
    """Analyze response on an output-Nyquist normalized frequency axis."""
    mode_l = (mode or '').lower()
    is_interpolator = 'interpolator' in mode_l
    use_fir = 'fir' in mode_l

    if use_fir:
        try:
            fir_shift, coeffs_verilog = calculate_fir_params(
                N, R, M, taps, passband_ratio, coeff_width, window_type,
                antisymmetric, 'interpolator' if is_interpolator else 'decimator'
            )
        except ValueError:
            fir_shift = 0
            coeffs_verilog = ["16'sd1"]

        coeffs_int = []
        for c_str in coeffs_verilog:
            try:
                if "'sd" not in c_str:
                    raise ValueError(f"格式不符: {c_str!r}")
                val_str = c_str.split("'sd")[-1]
                val = int(val_str)
                if c_str.startswith("-"):
                    val = -val
                coeffs_int.append(val)
            except (ValueError, IndexError):
                coeffs_int.append(0)
        coeffs_float = np.array(coeffs_int) / (2.0 ** fir_shift)
    else:
        coeffs_float = None

    num_points = 4096
    freqs_norm_out_nyq = np.linspace(0, 1.0, num_points)

    if is_interpolator:
        cic_freqs = freqs_norm_out_nyq / 2.0
        fir_w = np.pi * freqs_norm_out_nyq * R
    else:
        cic_freqs = freqs_norm_out_nyq / (2.0 * R)
        fir_w = np.pi * freqs_norm_out_nyq

    h_cic = get_cic_response_raw(cic_freqs, R, N, M)
    if use_fir:
        _, h_fir = signal.freqz(coeffs_float, 1, worN=fir_w)
    else:
        h_fir = np.ones_like(h_cic)

    h_total = h_cic * np.abs(h_fir)

    with np.errstate(divide='ignore'):
        mag_cic = 20 * np.log10(h_cic + 1e-15)
        mag_fir = 20 * np.log10(np.abs(h_fir) + 1e-15)
        mag_tot = 20 * np.log10(h_total + 1e-15)

    return freqs_norm_out_nyq, mag_cic, mag_fir, mag_tot


def estimate_fpga_resource(N, M, R, data_width, taps=0):
    """
    Estimate FPGA resource usage for CIC (+ optional FIR) filter.

    Returns dict with keys: cic, fir, total. Each sub-dict has luts, ffs, dsps.
    taps=0 means CIC-only (no FIR resources estimated).
    """
    bit_growth = calc_cic_growth(N, M, R)
    internal_width = data_width + bit_growth

    cic_luts = int(internal_width * N * 1.5)
    cic_ffs = int(internal_width * N * 2)

    if taps > 0:
        fir_dsps = (taps + 1) // 2
        fir_luts = taps * 15
        fir_ffs = taps * data_width + 50
    else:
        fir_dsps = 0
        fir_luts = 0
        fir_ffs = 0

    total_luts = cic_luts + fir_luts
    total_ffs = cic_ffs + fir_ffs
    total_dsps = fir_dsps

    return {
        "cic": {"luts": cic_luts, "ffs": cic_ffs, "internal_width": internal_width},
        "fir": {"luts": fir_luts, "ffs": fir_ffs, "dsps": fir_dsps},
        "total": {"luts": total_luts, "ffs": total_ffs, "dsps": total_dsps},
    }
