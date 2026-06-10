# DM-NAX-X300 Test Suite

Automated test suite for DM-NAX-X300 and STM32MP1-based audio devices.

## Overview

This test suite is specifically designed for **STM32MP1-based** DM-NAX devices, which use a different hardware architecture than the FPGA-based devices (8ZSA/4ZSA/4ZSP).

### Supported Devices

- **DM-NAX-X300** - STM32MP1-based audio matrix
- **DM-NAX-XLR** - XLR input/output module
- **DM-NAX-BTIO** - Bluetooth I/O module
- **DM-NAX-AUD-USB** - USB audio interface
- **DM-NAX-AUD-IO** - Audio I/O module
- **DM-NAX-POE-SPK** - PoE speaker module
- **Gemini DECT (FLEX-HUB)** - DECT wireless hub

## Architecture Differences from FPGA Devices

| Feature | FPGA Devices (8ZSA/4ZSA) | STM32MP1 Devices (X300) |
|---------|--------------------------|-------------------------|
| Processor | Altera Cyclone V FPGA + SHARC DSP | STMicroelectronics STM32MP157 (ARM) |
| Firmware | fw21/fw42 DSP firmware | STM32MP1 Linux-based firmware |
| Build System | build-dmnax-intel.sh | build-x300-dunfell.sh |
| DSP Commands | `dsp tone`, `dsp mix`, `dsp` | `dsp_test tone`, `dsp_test mix`, `dsp_test` |
| Audio Architecture | SHARC DSP blocks | ARM-based audio processing |
| SSH Port | 22 (standard) | 6022 for bash, 22 for custom console |

## X300 Operating Modes

The DM-NAX-X300 supports two operating modes that affect zone configuration:

### Residential Mode (Mode 0)
- **2 zones** (stereo)
- Each zone has left and right channels
- Zone 1 = Output channels 0-1 (L/R)
- Zone 2 = Output channels 2-3 (L/R)

### Commercial Mode (Mode 1)
- **4 channels** (mono)
- Each channel is independent
- Channel 1 = Output channel 0
- Channel 2 = Output channel 1
- Channel 3 = Output channel 2
- Channel 4 = Output channel 3

**DSP Mode Commands:**
```bash
# Read current mode
dsp_test mode

# Set to residential mode (0)
dsp_test mode 0

# Set to commercial mode (1)
dsp_test mode 1
```

**Python API:**
```python
from lib.x300_controller import X300Controller

with X300Controller(config) as controller:
    # Get current mode
    mode = controller.get_mode()  # Returns 'residential' or 'commercial'
    
    # Get zone count based on mode
    zones = controller.get_zone_count()  # Returns 2 or 4
    
    # Set mode
    controller.set_mode('residential')  # or 'commercial'
```

## Back Panel Switches

The X300 has 4 physical DIP switches on the back panel that can be read via the test suite:

### 1. Power Mode Switch (Pwr Saver / Always On)
Controls amplifier power management:
-  **Position 0:** Power Saver mode
- **Position 1:** Always On mode

### 2. Impedance Switch (LoZ / 70V-100V)
Controls speaker impedance mode:
- **Position 0:** LoZ (Low Impedance)
- **Position 1:** 70V/100V (High Impedance)

### 3. Zone 1 Mode Switch (Ch 1-2: Stereo / Sum / Bridge)
Controls operating mode for channels 1-2:
- **Position 0:** Bridge/Sum mode
- **Position 1:** Stereo mode

### 4. Zone 2 Mode Switch (Ch 3-4: Stereo / Sum / Bridge)
Controls operating mode for channels 3-4:
- **Position 0:** Bridge/Sum mode
- **Position 1:** Stereo mode

**Read switch positions:**
```bash
# Quick view of all switches
./show_switches.py

# Or via Python API
python3 << 'EOF'
import sys
sys.path.insert(0, '.')
from lib.x300_controller import X300Controller

config = {
    'ip': '192.168.1.246',
    'username': 'admin',
    'password': 'admin123',
    'ssh_port': 6022,
    'model': 'X300'
}

with X300Controller(config) as controller:
    switches = controller.get_all_back_panel_switches()
    print(f"Power Mode: {'Always On' if switches['power_mode'] else 'Power Saver'}")
    print(f"Impedance: {'70V/100V' if switches['impedance'] else 'LoZ'}")
    print(f"Zone 1 (Ch 1-2): {'Stereo' if switches['zone1_mode'] else 'Bridge/Sum'}")
    print(f"Zone 2 (Ch 3-4): {'Stereo' if switches['zone2_mode'] else 'Bridge/Sum'}")
EOF
```

**Test switch reading:**
```bash
# Test all switches
pytest tests/test_basic_connectivity.py::TestBackPanelSwitches -v

# Test individual switches
pytest tests/test_basic_connectivity.py::TestBackPanelSwitches::test_read_power_mode_switch -v
pytest tests/test_basic_connectivity.py::TestBackPanelSwitches::test_read_impedance_switch -v
pytest tests/test_basic_connectivity.py::TestBackPanelSwitches::test_read_zone1_mode_switch -v
pytest tests/test_basic_connectivity.py::TestBackPanelSwitches::test_read_zone2_mode_switch -v
```

**Note:** Switches are **read-only** - they reflect physical hardware positions and cannot be controlled via software.

## Installation

```bash
cd DM-NAX-X300_test_suite
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Edit `config/devices.yaml` to configure your X300 device(s):

```yaml
devices:
  DM-NAX-X300-001:
    ip: "10.x.x.x"
    username: "admin"
    password: "crestron"
    model: "X300"
```

## Running Tests

**By default, the test suite will prompt you for IP address, username, and password when you run it.**

```bash
# Run all tests (will prompt for IP, username, password)
./run_tests.sh

# Skip prompts and use config file
./run_tests.sh --skip-prompt

# Or use pytest directly (will also prompt)
pytest -v

# Set via environment variables (no prompt)
export X300_IP=192.168.1.246
export X300_USERNAME=admin
export X300_PASSWORD=admin123
./run_tests.sh

# Quick mode (subset of tests, will prompt)
./run_tests.sh --quick

# Quick mode without prompt
pytest -m quick -v --skip-prompt
```

### Configuration Options:

1. **Interactive prompt (default)** - You'll be asked for IP, username, password
2. **Environment variables** - Set `X300_IP`, `X300_USERNAME`, `X300_PASSWORD`
3. **Config file** - Edit [config/devices.yaml](config/devices.yaml) and use `--skip-prompt`

See [docs/CREDENTIALS.md](docs/CREDENTIALS.md) for detailed configuration options.

## Test Categories

- **Audio Routing** - Input to output signal routing
- **Volume Control** - Zone volume adjustment and mute
- **Network Audio** - Streaming audio over network (if applicable)
- **GPIO/Control** - GPIO pins and control interfaces
- **Power Management** - Power states and PoE (if applicable)
- **Firmware Upgrade** - Over-the-air firmware updates

## Development

To add support for a new STM32MP1-based device:

1. Add device configuration to `config/devices.yaml`
2. Update device-specific commands in `lib/device_controller.py`
3. Add test cases as needed

## Directory Structure

```
DM-NAX-X300_test_suite/
├── config/          # Device configurations
├── lib/             # Test libraries and device controllers
├── tests/           # Test modules
├── docs/            # Documentation
├── deploy/          # Deployment scripts
├── templates/       # Report templates
├── conftest.py      # Pytest configuration
└── run_tests.sh     # Test runner script
```

## Notes

- This test suite is **separate** from the FPGA-based DM-NAX test suite
- X300 devices use different firmware and require different test approaches
- See the feature/x300 branch for work-in-progress X300 support

## References

- Build script: `/home/rhudes/Linux_jstr1000/build-x300-dunfell.sh`
- Custom files: `/home/rhudes/Linux_jstr1000/customFiles_stm/stm32mp1/`
- Main repo: https://nj-github.crestron.crestron.com/CrestronEngineering/DM-NAX_test_suite.git
