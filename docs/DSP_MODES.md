# X300 DSP Operating Modes

## Overview

The DM-NAX-X300 supports two distinct operating modes that fundamentally change how audio zones and channels are configured: **Residential** and **Commercial** mode.

## Mode Comparison

| Feature | Residential Mode (0) | Commercial Mode (1) |
|---------|---------------------|---------------------|
| **Configuration** | 2 stereo zones | 4 mono channels |
| **Total Channels** | 4 (2 zones × 2 channels) | 4 independent channels |
| **Use Case** | Home audio, stereo music | Commercial installations, PA systems |
| **Zone Concept** | Zones with L/R channels | Individual channel control |
| **Input Sources** | Stereo inputs | Mono inputs |

## Hardware Amplifier Limitation

**IMPORTANT:** Regardless of DSP mode (residential or commercial), the **amplifier hardware** can only be controlled by zone pairs:

- **Amplifier Zone 1**: Controls output channels 0-1
- **Amplifier Zone 2**: Controls output channels 2-3

This means:
- In **Residential Mode**: Amp control aligns with audio zones (1:1 mapping)
  - Audio Zone 1 (stereo) = Amp Zone 1 (channels 0-1)
  - Audio Zone 2 (stereo) = Amp Zone 2 (channels 2-3)

- In **Commercial Mode**: Each amp zone controls 2 mono channels
  - Amp Zone 1 controls both Channel 1 (output 0) and Channel 2 (output 1)
  - Amp Zone 2 controls both Channel 3 (output 2) and Channel 4 (output 3)
  - **You cannot enable/disable individual channels at the amplifier level**

**Amplifier Control via sysfs:**
```bash
# Enable/disable amp zones
echo 1 > /sys/class/leds/AMP_ENABLE_Z1/brightness  # Enable zone 1 (ch 0-1)
echo 0 > /sys/class/leds/AMP_ENABLE_Z1/brightness  # Disable zone 1

echo 1 > /sys/class/leds/AMP_ENABLE_Z2/brightness  # Enable zone 2 (ch 2-3)
echo 0 > /sys/class/leds/AMP_ENABLE_Z2/brightness  # Disable zone 2

# Check amp zone status
cat /sys/class/leds/AMP_ENABLE_Z1/brightness  # Returns 0 or 1
cat /sys/class/leds/AMP_ENABLE_Z2/brightness  # Returns 0 or 1

# Always-on mode (keeps amps on regardless of signal)
echo 1 > /sys/class/leds/AMP_ALWAYS_ON/brightness  # Enable always-on
echo 0 > /sys/class/leds/AMP_ALWAYS_ON/brightness  # Disable always-on

# Signal sense (auto-on when signal detected)
echo 1 > /sys/class/leds/AMP_SIGNAL_SENSE/brightness  # Enable signal sense
echo 0 > /sys/class/leds/AMP_SIGNAL_SENSE/brightness  # Disable signal sense
```

**Python API:**
```python
from lib.x300_controller import X300Controller

with X300Controller(config) as controller:
    # Enable/disable amp zones
    controller.enable_amp_zone(1)   # Enable zone 1 (channels 0-1)
    controller.disable_amp_zone(1)  # Disable zone 1
    
    controller.enable_amp_zone(2)   # Enable zone 2 (channels 2-3)
    controller.disable_amp_zone(2)  # Disable zone 2
    
    # Check amp zone status
    zone1_on = controller.get_amp_zone_status(1)  # Returns True/False
    zone2_on = controller.get_amp_zone_status(2)  # Returns True/False
    
    # Always-on mode
    controller.set_amp_always_on(True)   # Enable always-on
    controller.set_amp_always_on(False)  # Disable always-on
    always_on = controller.get_amp_always_on()  # Returns True/False
    
    # Signal sense
    controller.set_signal_sense(True)   # Enable signal sense
    controller.set_signal_sense(False)  # Disable signal sense
    sense_on = controller.get_signal_sense()  # Returns True/False
```

## Residential Mode

**Characteristics:**
- 2 stereo zones
- Each zone has left (L) and right (R) channels
- Designed for residential music systems
- Maintains stereo imaging

**Zone Mapping:**
- Zone 1:
  - Left channel = Output 0
  - Right channel = Output 1
- Zone 2:
  - Left channel = Output 2
  - Right channel = Output 3

**Example Use Cases:**
- Living room stereo speakers
- Outdoor patio audio
- Multi-room whole-house audio systems

## Commercial Mode

**Characteristics:**
- 4 independent mono channels
- Each channel operates independently
- Designed for commercial audio distribution
- Optimized for voice paging and announcements

**Channel Mapping:**
- Channel 1 = Output 0
- Channel 2 = Output 1
- Channel 3 = Output 2
- Channel 4 = Output 3

**Inputs (Commercial Mode):**
According to firmware code (`zoneRoutes.cpp`):
- 4 × Analog inputs (Input01-04)
- 4 × AES67 RX inputs (aes67Rx01-04)
- 1 × Signal generator (signalGen)
- **Total: 9 input sources**

**Example Use Cases:**
- Retail stores with separate zones
- Restaurants/bars with independent area control
- Office buildings with paging systems
- Conference rooms with separate audio feeds

## Switching Modes

### Reading Current Mode (Via SSH)

```bash
# Connect to X300 via SSH (port 6022)
ssh -p 6022 admin@192.168.1.246

# Check current mode
dsp_test mode
# Output: "DSP mode is  Residential" or "DSP mode is  Commercial"
```

### Changing Modes (Console Only)

**IMPORTANT:** Mode changes MUST be done from device console using `aconfigcontrol`.
This ensures ALL components (DSP, AMP control, etc.) are synchronized.

```bash
# Connect to device console (serial or web interface)
# At DM-NAX-AMP-X300> prompt:

# Set to residential mode
aconfigcontrol setresidboot

# Set to commercial mode
aconfigcontrol setcommeboot

# Reboot device for changes to take effect
reboot

# After reboot, verify via SSH:
dsp_test mode
```

**WARNING:** Do NOT use `dsp_test mode 0/1` to change modes. This only changes
the DSP component and will cause mismatches with other system components!

### Via Python Test Suite

```python
from lib.x300_controller import X300Controller

# Create controller
config = {
    'ip': '192.168.1.246',
    'username': 'admin',
    'password': 'admin123',
    'model': 'X300',
    'platform': 'STM32MP1',
    'ssh_port': 6022
}

with X300Controller(config) as controller:
    # Get current mode
    current_mode = controller.get_mode()
    print(f"Current mode: {current_mode}")
    
    # Get zone/channel count
    count = controller.get_zone_count()
    print(f"Zone/channel count: {count}")
    
    # Switch to residential mode
    controller.set_mode('residential')
    
    # Switch to commercial mode
    controller.set_mode('commercial')
```

## Firmware Implementation

The mode selection is implemented in the firmware at:

- **`src/DspAudioCtl/AvMatrixRouting/zoneManagerMain.cpp`**
  - Selects zone manager based on mode:
    - `NAX_AUDIOMODE_RESIDENTIAL` → `DNAX300IPresidential`
    - `NAX_AUDIOMODE_COMMERCIAL` → `DNAX300IPcommercial`

- **`src/DspAudioCtl/AvMatrixRouting/zoneRoutes.cpp`**
  - Defines input/output routing matrices:
    - `DSP_MATRIX_INPUTS_COMMERCIAL` - 9 input sources
    - `DSP_MATRIX_OUTPUTS_COMMERCIAL` - 4 output channels

- **`src/DspAudioCtl/test/dsp_test.c`**
  - Implements `mode` command in `dsp_test` utility
  - Function: `run_dsp_mode()` at line 5479
  - Uses `AUDIO_DSP_CMD_STATE_CFG` ioctl to read/write mode

## Zone Manager Classes

### Residential Zone Manager (`DNAX300IPresidential`)
- Manages 2 stereo zones
- Routes inputs to L/R channel pairs
- Maintains stereo balance and imaging

### Commercial Zone Manager (`DNAX300IPcommercial`)
- Manages 4 independent mono channels
- Individual channel control
- Optimized for commercial audio distribution

## Testing Modes

The test suite includes comprehensive mode testing:

```bash
# Run mode tests
pytest tests/test_basic_connectivity.py::TestDSPModes -v

# Test getting current mode
pytest tests/test_basic_connectivity.py::TestDSPModes::test_get_current_mode -v

# Test zone count detection
pytest tests/test_basic_connectivity.py::TestDSPModes::test_get_zone_count -v

# Test mode switching (both residential and commercial)
pytest tests/test_basic_connectivity.py::TestDSPModes::test_set_mode -v
```

## Best Practices

1. **Check mode before audio operations** - Zone count varies by mode
2. **Document mode in configuration** - Note which mode is expected for deployment
3. **Test both modes** - Ensure firmware supports both configurations
4. **Restore original mode** - After testing, restore device to original state
5. **Consider user expectations** - Residential users expect stereo, commercial users need flexibility

## Mode Persistence

The DSP mode setting is:
- Stored in DSP state configuration
- Persists across DSP restarts (`dsp_test start`)
- May or may not persist across power cycles (verify with hardware team)

**Recommendation:** Set mode during device provisioning/configuration via CresNext API.

## CresNext API Integration

For production systems, mode should be configurable through the CresNext web API:
- Check if `/api/dsp/mode` endpoint exists
- Document API integration for installer configuration
- Consider adding mode selection to device setup wizard

## Troubleshooting

### Mode Switch Not Taking Effect
```bash
# Verify mode was set
dsp_test mode

# Restart DSP processing
dsp_test start

# Check status table shows correct mode
dsp_test
# Look for [Mode:RESI] or [Mode:COMM] in output
```

### Zone Count Mismatch
```python
# Always query zone count after connecting
with X300Controller(config) as controller:
    mode = controller.get_mode()
    zones = controller.get_zone_count()
    print(f"Mode: {mode}, Zones: {zones}")
```

### Testing in Wrong Mode
- Always verify mode before running audio tests
- Use `@pytest.fixture` to set mode at test start
- Restore original mode after test completion

## See Also

- [ARCHITECTURE.md](ARCHITECTURE.md) - X300 hardware architecture
- [QUICK_START.md](QUICK_START.md) - Getting started guide
- [src/DspAudioCtl/AvMatrixRouting/](../../src/DspAudioCtl/AvMatrixRouting/) - Zone manager source code
