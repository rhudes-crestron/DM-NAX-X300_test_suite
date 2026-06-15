"""
DSP output parser - converts raw `dsp` command output into structured data.
Parses the SHARC DSP status table with input channels, mixer levels, and output levels.
"""
import re
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class InputChannel:
    index: int
    name: str
    routed: bool
    vcg: str
    ag: str
    dv_o: str
    has_adc: bool
    test_freq: int
    test_gain_db: float
    gain_db: float          # Input compensation / gain
    level_db: float         # Measured input level

    @property
    def is_signal_present(self):
        return self.level_db > -110.0


@dataclass
class OutputChannel:
    index: int
    name: str
    balance_db: float
    trim: float
    ducker_db: float
    agc_db: float
    agc_gain_db: float
    limiter_db: float
    output_db: float        # Final output level
    invert: float
    delay_ms: int
    is_passthrough: bool
    passthrough_input: str
    passthrough_level_db: float

    @property
    def is_signal_present(self):
        return self.output_db > -110.0


@dataclass
class MixerNode:
    input_idx: int
    input_name: str
    output_idx: int
    output_name: str
    gain_db: float


@dataclass
class DSPState:
    model: str = ""
    fw_version: int = 0
    sw_version: str = ""
    master_volume_db: float = 0.0
    recovery_clock: int = 0
    inputs: dict = field(default_factory=dict)     # name -> InputChannel
    outputs: dict = field(default_factory=dict)     # name -> OutputChannel
    mixer: list = field(default_factory=list)       # MixerNode list


def _parse_float(s):
    """Parse a float from DSP output, handling -inf and whitespace."""
    s = s.strip()
    if s == "-inf" or s == "":
        return float("-inf")
    try:
        return float(s)
    except ValueError:
        return float("-inf")


def _parse_int(s, default=0):
    s = s.strip()
    try:
        return int(s)
    except ValueError:
        return default


def parse_dsp_output(raw_output):
    """Parse the full `dsp` command output into a DSPState object.

    Supports three firmware formats:
      - fw21 (4ZSA): |00|S1L  |-|...  |     A1L|  0|
      - fw42 (4ZSP/8ZSA): | T1L |(  0.0) -inf |  | 0| Z1L |...
      - fw36 (X300): |00| L1 |E| 13|   -inf  ... |  A1| 0|x-|0|0| |
    Auto-detects format from the output content.
    """
    state = DSPState()
    lines = raw_output.strip().split("\n")

    # Parse header: DSP[4ZSA:0x2]: FW version 21, SW driver version 4.3
    for line in lines:
        m = re.search(r"DSP\[(\w+):.*FW version (\d+),\s*SW driver version ([\d.]+)", line)
        if m:
            state.model = m.group(1)
            state.fw_version = int(m.group(2))
            state.sw_version = m.group(3)

        m = re.search(r"RecovClk:\s*(\d+)", line)
        if m:
            state.recovery_clock = int(m.group(1))

        m = re.search(r"Master Vol(?:ume)?:\s*([-\d.]+)\s*dB", line)
        if m:
            state.master_volume_db = float(m.group(1))

    # Detect fw36 format (X300): contains "[Mode:RESI]" in header
    is_fw36 = any("[Mode:RESI]" in line or "[Mode:COMM]" in line for line in lines)
    
    # Detect fw42 format: header lines contain "Amp" and "flow" (on separate lines)
    is_fw42 = (any("| Amp |" in line for line in lines)
               and any("| flow|" in line for line in lines))

    if is_fw36:
        _parse_fw36_data(lines, state)
    elif is_fw42:
        _parse_fw42_data(lines, state)
    else:
        _parse_fw21_data(lines, state)

    return state


# Zone-name to amp-name mapping so tests written for A1L/A1R still work on fw42
_ZONE_TO_AMP = {}
for _z in range(1, 9):
    _ZONE_TO_AMP[f"Z{_z}L"] = f"A{_z}L"
    _ZONE_TO_AMP[f"Z{_z}R"] = f"A{_z}R"


def _parse_fw42_data(lines, state):
    """Parse fw42 format (4ZSP / 8ZSA).

    Data rows:
    | T1L |(  0.0)    -inf |  | 0| Z1L |1000@ -20 (  0.0/  0.0)  -20.11 |(  0.0)  -20.12  -20.11 (  0.0/  0.0)  -20.11  -20.12/ -20.11 |

    Sections separated by '|':
      [1] InputName    [2] (InputGain) InputLevel    [3] blank
      [4] ch           [5] OutputName
      [6] [Freq@dB] (Bal/Gain) MixerLevel
      [7] (Trim) Ducker AGC (GainL/GainA) Lim OutL/OutA
    """
    # Match data rows: starts with "| " followed by a channel name like T1L, S1L, A1L
    row_re = re.compile(r"^\|\s+(\w+)\s+\|")

    for line in lines:
        rm = row_re.match(line)
        if not rm:
            continue

        input_name = rm.group(1)

        # Split by "|" — parts[0] is empty (before first |)
        parts = [p for p in line.split("|")]
        # Typical split: ['', ' T1L ', '(  0.0)    -inf ', '  ', ' 0', ' Z1L ', '...', '...', '']
        if len(parts) < 8:
            continue

        # --- Input side ---
        input_section = parts[2]  # "(  0.0)    -inf"
        input_gain_m = re.search(r"\(\s*([-\d.]+)\)", input_section)
        input_level_m = re.search(r"\)\s+([-\d.inf]+)", input_section)
        gain_db = _parse_float(input_gain_m.group(1)) if input_gain_m else 0.0
        input_level = _parse_float(input_level_m.group(1)) if input_level_m else float("-inf")

        # Channel index
        ch_str = parts[4].strip()
        ch_idx = _parse_int(ch_str)

        # Output name (zone name like Z1L)
        out_name_raw = parts[5].strip()

        # Mixer/FPGA input section — may contain tone info
        fpga_section = parts[6] if len(parts) > 6 else ""
        test_freq = 0
        test_gain_db = float("-inf")
        tone_m = re.search(r"(\d+)@\s*([-\d.inf]+)", fpga_section)
        if tone_m:
            test_freq = _parse_int(tone_m.group(1))
            test_gain_db = _parse_float(tone_m.group(2))

        # Mixer level: (Bal/Gain) Level
        mixer_level = float("-inf")
        bal_gain_m = re.search(r"\(\s*([-\d.inf]+)\s*/\s*([-\d.inf]+)\)\s+([-\d.inf]+)", fpga_section)
        balance_db = 0.0
        trim_db = 0.0
        if bal_gain_m:
            balance_db = _parse_float(bal_gain_m.group(1))
            trim_db = _parse_float(bal_gain_m.group(2))
            mixer_level = _parse_float(bal_gain_m.group(3))

        # --- Input channel ---
        inp = InputChannel(
            index=ch_idx, name=input_name, routed=True,
            vcg="", ag="", dv_o="", has_adc=False,
            test_freq=test_freq, test_gain_db=test_gain_db,
            gain_db=gain_db, level_db=input_level,
        )
        state.inputs[input_name] = inp

        # --- Output side ---
        # Section: "(  0.0)  -20.12  -20.11 (  0.0/  0.0)  -20.11  -20.12/ -20.11"
        out_section = parts[7] if len(parts) > 7 else ""

        ducker_db = float("-inf")
        agc_db = float("-inf")
        agc_gain_db = 0.0
        limiter_db = float("-inf")
        output_db = float("-inf")
        out_trim = 0.0

        # Parse: (Trim) Ducker AGC (GainL/GainA) Lim OutL/OutA
        out_m = re.search(
            r"\(\s*([-\d.inf]+)\)\s+"            # trim
            r"([-\d.inf]+)\s+"                    # ducker
            r"([-\d.inf]+)\s+"                    # agc
            r"\(\s*([-\d.inf]+)\s*/\s*([-\d.inf]+)\)\s+"  # gain_l / gain_a
            r"([-\d.inf]+)\s+"                    # limiter
            r"([-\d.inf]+)\s*/\s*([-\d.inf]+)",   # outL / outA
            out_section
        )
        if out_m:
            out_trim = _parse_float(out_m.group(1))
            ducker_db = _parse_float(out_m.group(2))
            agc_db = _parse_float(out_m.group(3))
            agc_gain_db = _parse_float(out_m.group(4))
            limiter_db = _parse_float(out_m.group(6))
            output_db = _parse_float(out_m.group(8))  # use A (amp) value — post-EQ

        # Map zone name to amp name for test compatibility (Z1L → A1L)
        mapped_name = _ZONE_TO_AMP.get(out_name_raw, out_name_raw)

        out = OutputChannel(
            index=ch_idx, name=mapped_name,
            balance_db=balance_db, trim=out_trim,
            ducker_db=ducker_db, agc_db=agc_db,
            agc_gain_db=agc_gain_db, limiter_db=limiter_db,
            output_db=output_db, invert=0, delay_ms=0,
            is_passthrough=False, passthrough_input="",
            passthrough_level_db=float("-inf"),
        )
        # Store under both the mapped name AND original zone name
        state.outputs[mapped_name] = out
        if mapped_name != out_name_raw:
            state.outputs[out_name_raw] = out


def _parse_fw36_data(lines, state):
    """Parse fw36 format (X300).

    Data rows:
    |00| L1 |E| 13|   -inf    0@-inf (  0.0)    -inf |   -inf|00|(  0.0/  0.0)    -inf    -inf ( -2.0) (  0.0)    -inf    -inf |  A1| 0|x-|0|0| |
    
    Sections separated by '|':
      [1] Input channel index (00-11)
      [2] Input name (L1-L4, N1-N4, SG)
      [3] P flag (E for enabled, blank otherwise)
      [4] PGA value (ADC gain)
      [5] Raw Level, Test (freq@gain), Input Gain, Level
      [6] Mixer Level
      [7] Output channel index (00-11)
      [8] Balance/Trim, Ducker, AGC, (Trim), (Gain), Limiter, Output
      [9] Output name (A1-A4, L1-L4, N1-N4)
      [10+] Additional flags (D, RM, A, B, R)
    """
    # Match data rows: starts with "|" followed by 2-digit channel index
    row_re = re.compile(r"^\|(\d{2})\|\s*(\w*)\s*\|")

    for line in lines:
        rm = row_re.match(line)
        if not rm:
            continue

        input_idx_str = rm.group(1)
        input_name = rm.group(2).strip()
        
        # Skip rows with no input name (continuation rows for signal generator)
        if not input_name:
            continue

        input_idx = int(input_idx_str)

        # Split by "|" — parts[0] is empty (before first |)
        parts = [p for p in line.split("|")]
        if len(parts) < 10:
            continue

        # --- Input section ---
        # parts[1] = input index (already parsed)
        # parts[2] = input name (already parsed)
        # parts[3] = P flag
        # parts[4] = PGA value
        # parts[5] = input levels and test tone info
        input_section = parts[5]  # "   -inf    0@-inf (  0.0)    -inf"
        
        # Parse test tone: freq@gain
        test_freq = 0
        test_gain_db = float("-inf")
        tone_m = re.search(r"(\d+)@\s*([-\d.inf]+)", input_section)
        if tone_m:
            test_freq = int(tone_m.group(1))
            test_gain_db = _parse_float(tone_m.group(2))

        # Parse input gain: (value)
        input_gain_m = re.search(r"\(\s*([-\d.]+)\)", input_section)
        input_gain_db = _parse_float(input_gain_m.group(1)) if input_gain_m else 0.0

        # Parse input level: last value in section
        level_parts = input_section.split()
        input_level_db = _parse_float(level_parts[-1]) if level_parts else float("-inf")

        # --- Mixer section ---
        mixer_level = _parse_float(parts[6].strip()) if parts[6].strip() else float("-inf")

        # --- Output section ---
        # parts[7] = output index
        output_idx_str = parts[7].strip()
        if not output_idx_str or not output_idx_str.isdigit():
            # Some rows may not have output section
            continue
        output_idx = int(output_idx_str)

        # parts[8] = output processing chain
        output_section = parts[8]  # "(  0.0/  0.0)    -inf    -inf ( -2.0) (  0.0)    -inf    -inf"
        
        # Parse Balance / Trim: (bal / trim)
        bal_trim_m = re.search(r"\(\s*([-\d.inf]+)\s*/\s*([-\d.inf]+)\)", output_section)
        balance_db = 0.0
        trim_db = 0.0
        if bal_trim_m:
            balance_db = _parse_float(bal_trim_m.group(1))
            trim_db = _parse_float(bal_trim_m.group(2))

        # Parse output values: after balance/trim, we have: ducker agc (trim) (gain) lim output
        # Split and extract values
        values = []
        # Remove parenthesized values and extract remaining numbers
        cleaned = re.sub(r'\([^)]+\)', '', output_section)
        for match in re.finditer(r'[-\d.inf]+', cleaned):
            values.append(_parse_float(match.group()))

        # Extract values (may vary, so handle gracefully)
        ducker_db = values[0] if len(values) > 0 else float("-inf")
        agc_db = values[1] if len(values) > 1 else float("-inf")
        limiter_db = values[2] if len(values) > 2 else float("-inf")
        output_db = values[3] if len(values) > 3 else float("-inf")

        # parts[9] = output name
        output_name = parts[9].strip()

        # --- Create input channel ---
        in_ch = InputChannel(
            index=input_idx, name=input_name, routed=True,
            vcg="", ag="", dv_o="", has_adc=(parts[3].strip() == "E"),
            test_freq=test_freq, test_gain_db=test_gain_db,
            gain_db=input_gain_db, level_db=input_level_db
        )
        state.inputs[input_name] = in_ch

        # --- Create output channel ---
        out_ch = OutputChannel(
            index=output_idx, name=output_name,
            balance_db=balance_db, trim=trim_db,
            ducker_db=ducker_db, agc_db=agc_db, agc_gain_db=0.0,
            limiter_db=limiter_db, output_db=output_db,
            invert=0, delay_ms=0,
            is_passthrough=False, passthrough_input="",
            passthrough_level_db=float("-inf")
        )
        state.outputs[output_name] = out_ch


def _parse_fw21_data(lines, state):
    """Parse fw21 format (4ZSA)."""
    data_pattern = re.compile(
        r"\|(\d+)\|(\w+)\s*\|(.)\|"   # index, name, route flag
    )

    for line in lines:
        if not line.startswith("|") or line.startswith("|#") or line.startswith("|--") or line.startswith("|-"):
            continue

        m = data_pattern.match(line)
        if not m:
            continue

        idx = int(m.group(1))
        name = m.group(2).strip()
        routed = m.group(3).strip()

        # Split on the main pipe separator between input and output sections
        # The format uses | characters extensively, so we parse by position
        parts = line.split("|")
        if len(parts) < 10:
            continue

        # --- Parse Input Side ---
        has_adc = False
        vcg = ag = dv_o = ""
        test_freq = 0
        test_gain_db = float("-inf")
        gain_db = 0.0
        level_db = float("-inf")

        # ADC columns (VCG, AG, DV+O) - present for line inputs
        adc_section = parts[4] if len(parts) > 4 else ""
        if adc_section.strip():
            has_adc = True
            vcg = adc_section.strip()

        # Input Gain and Level
        input_data_section = ""
        for i, p in enumerate(parts):
            if "Test f@dB" in p or "Gain" in p:
                break
            if i >= 7 and "(" in p:
                input_data_section = p
                break

        # Search for gain and level in the input data area
        # Pattern: (  6.0)  -14.11
        gain_level_match = re.search(r"\(\s*([-\d.]+)\)\s+([-\d.inf]+)", line)
        if gain_level_match:
            gain_db = _parse_float(gain_level_match.group(1))
            level_db = _parse_float(gain_level_match.group(2))

        # Test tone: 1000@ -20
        tone_match = re.search(r"(\d+)@\s*([-\d.inf]+)", line)
        if tone_match:
            test_freq = _parse_int(tone_match.group(1))
            test_gain_db = _parse_float(tone_match.group(2))

        inp = InputChannel(
            index=idx, name=name, routed=(routed != "-" and routed != " "),
            vcg=vcg, ag=ag, dv_o=dv_o, has_adc=has_adc,
            test_freq=test_freq, test_gain_db=test_gain_db,
            gain_db=gain_db, level_db=level_db,
        )
        state.inputs[name] = inp

        # --- Parse Output Side ---
        # Look for the output section after the mixer column
        # Pattern: |00| (  0.0/  1.0)  -20.11  -20.12 (-50.0)  -69.12  -69.13 -1.00 |     A1L|
        out_match = re.search(
            r"\|\s*(\d+)\|\s*"                             # output index
            r"\(\s*([-\d.inf]+)\s*/\s*([-\d.inf]+)\)\s*"   # balance / trim
            r"([-\d.inf]+)\s+"                              # ducker
            r"([-\d.inf]+)\s+"                              # agc
            r"\(\s*([-\d.inf]+)\)\s+"                       # agc gain
            r"([-\d.inf]+)\s+"                              # limiter
            r"([-\d.inf]+)\s+"                              # output
            r"([-\d.inf]+)\s*\|\s*"                         # invert
            r"(\w+)\s*\|"                                   # output name
            r"\s*(\d*)\s*\|",                               # delay
            line
        )

        # Passthrough pattern: | *** NOT MIXABLE *** Passthrough input: S1L  | -14.11  |     N1L|
        pt_match = re.search(
            r"NOT MIXABLE.*Passthrough input:\s*(\w+)\s*\|\s*([-\d.inf]+)\s*\|\s*(\w+)\s*\|",
            line
        )

        if out_match:
            out_idx = int(out_match.group(1))
            out_name = out_match.group(10).strip()
            delay_str = out_match.group(11).strip()
            out = OutputChannel(
                index=out_idx, name=out_name,
                balance_db=_parse_float(out_match.group(2)),
                trim=_parse_float(out_match.group(3)),
                ducker_db=_parse_float(out_match.group(4)),
                agc_db=_parse_float(out_match.group(5)),
                agc_gain_db=_parse_float(out_match.group(6)),
                limiter_db=_parse_float(out_match.group(7)),
                output_db=_parse_float(out_match.group(8)),
                invert=_parse_float(out_match.group(9)),
                delay_ms=_parse_int(delay_str),
                is_passthrough=False, passthrough_input="",
                passthrough_level_db=float("-inf"),
            )
            state.outputs[out_name] = out
        elif pt_match:
            pt_input = pt_match.group(1).strip()
            pt_level = _parse_float(pt_match.group(2))
            out_name = pt_match.group(3).strip()
            out = OutputChannel(
                index=idx, name=out_name,
                balance_db=0, trim=0, ducker_db=float("-inf"),
                agc_db=float("-inf"), agc_gain_db=0,
                limiter_db=float("-inf"),
                output_db=pt_level, invert=0, delay_ms=0,
                is_passthrough=True, passthrough_input=pt_input,
                passthrough_level_db=pt_level,
            )
            state.outputs[out_name] = out


def parse_mixer_output(raw_output):
    """Parse the `dsp mix` command output into a list of MixerNode entries."""
    nodes = []
    lines = raw_output.strip().split("\n")

    # Parse header row for output names
    output_names = []
    for line in lines:
        if line.strip().startswith("|  \\ OUT"):
            # Next line has output names
            continue
        if line.strip().startswith("|IN \\"):
            header_parts = line.split("|")
            output_names = [p.strip() for p in header_parts[2:] if p.strip()]
            continue
        if not output_names:
            continue

        # Data row: |  0--S1L|  0.0  -inf  -inf ...
        m = re.match(r"\|\s*(\d+)--(\w+)\|(.+)\|", line)
        if m:
            in_idx = int(m.group(1))
            in_name = m.group(2)
            values_str = m.group(3)
            values = values_str.split()
            for out_idx, val_str in enumerate(values):
                gain = _parse_float(val_str)
                if gain > float("-inf") and out_idx < len(output_names):
                    nodes.append(MixerNode(
                        input_idx=in_idx, input_name=in_name,
                        output_idx=out_idx, output_name=output_names[out_idx],
                        gain_db=gain,
                    ))

    return nodes
