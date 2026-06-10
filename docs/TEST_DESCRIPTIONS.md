# DM-NAX-X300 Test Suite - Test Descriptions

This document describes what each test does, the steps involved, and expected results.

## Table of Contents
- [Basic Connectivity Tests](#basic-connectivity-tests)
- [Audio Routing Tests](#audio-routing-tests)
- [Configuration Tests](#configuration-tests)
- [DSP Mode Tests](#dsp-mode-tests)
- [Amplifier Control Tests](#amplifier-control-tests)

---

## Basic Connectivity Tests

### test_ssh_connection
**Purpose:** Verify SSH connection to X300 device works correctly.

**Steps:**
1. Connect to device via SSH on port 6022
2. Execute simple command: `echo 'test'`
3. Verify command output contains "test"
4. Disconnect from device

**Expected Results:**
- SSH connection successful
- Command executes and returns expected output
- Clean disconnection

**Pass Criteria:**
- No connection errors
- Output contains "test" string

---

### test_device_info
**Purpose:** Verify device information can be retrieved correctly.

**Steps:**
1. Connect to device via SSH
2. Read `/etc/os-release` to get firmware version
3. Collect device information (model, IP, platform)
4. Verify all required fields are present

**Expected Results:**
```python
{
    'model': 'X300',
    'ip': '192.168.1.246',
    'platform': 'STM32MP1',
    'firmware_version': 'v1.0' (or similar)
}
```

**Pass Criteria:**
- All required fields present
- Platform is "STM32MP1"
- Firmware version is readable

---

### test_uptime
**Purpose:** Verify device uptime can be queried.

**Steps:**
1. Connect to device via SSH
2. Execute: `uptime`
3. Verify output contains uptime information

**Expected Results:**
```
 10:45:32 up 2 days, 3:14, 1 user, load average: 0.05, 0.12, 0.09
```

**Pass Criteria:**
- Command returns output
- Output contains "load average" or "up"

---

## Audio Routing Tests

### test_route_input_to_output
**Status:** ⚠️ SKIPPED - Not yet implemented

**Purpose:** Verify audio routing from input to output via DSP mixer.

**Planned Steps:**
1. Connect to device
2. Start DSP processing: `dsp_test start`
3. Route input to output: `dsp_test mix <input> <output> <gain>`
4. Verify routing via mixer status

**Expected Results:**
- Audio routed from specified input to output
- Mixer gain set correctly
- Signal flows through routing path

---

### test_volume_control
**Purpose:** Verify zone volume control works correctly in both residential and commercial modes.

#### In Residential Mode (2 stereo zones):

**Steps:**
1. Connect to device and start DSP: `dsp_test start`
2. Get current mode: `dsp_test mode` → "Residential"
3. Set zone 1 volume to 0 dB
   - Zone 1 = Output channels 0 (L) and 1 (R)
   - Execute: `dsp_test gain 0 1 0` (channel 0, type 1=output gain, 0 dB)
   - Execute: `dsp_test gain 1 1 0` (channel 1, type 1=output gain, 0 dB)
4. Read back gain: `dsp_test gain 0 1` → verify 0 dB
5. Set zone 1 volume to -6 dB
   - Execute: `dsp_test gain 0 1 -6`
   - Execute: `dsp_test gain 1 1 -6`
6. Set zone 1 volume to -12 dB
   - Execute: `dsp_test gain 0 1 -12`
   - Execute: `dsp_test gain 1 1 -12`
7. Reset zone 1 volume to 0 dB

**Expected Results:**
- Gain commands execute successfully
- Both L and R channels set to same level (stereo)
- Volume changes take effect immediately
- Readback matches set value

**Zone Mapping (Residential):**
- Zone 1: Channels 0-1 (Left/Right)
- Zone 2: Channels 2-3 (Left/Right)

#### In Commercial Mode (4 mono channels):

**Steps:**
1. Connect to device and start DSP: `dsp_test start`
2. Get current mode: `dsp_test mode` → "Commercial"
3. Set channel 1 volume (output 0) to 0 dB
   - Execute: `dsp_test gain 0 1 0`
4. Set channel 1 volume to -6 dB
   - Execute: `dsp_test gain 0 1 -6`
5. Set channel 1 volume to -12 dB
   - Execute: `dsp_test gain 0 1 -12`
6. Reset to 0 dB

**Expected Results:**
- Each channel controlled independently
- Volume changes affect only specified channel
- No stereo pairing

**Channel Mapping (Commercial):**
- Channel 1: Output 0
- Channel 2: Output 1
- Channel 3: Output 2
- Channel 4: Output 3

**Pass Criteria:**
- All `dsp_test gain` commands succeed
- No errors in command output
- Volume changes audible (if monitoring)

---

## Configuration Tests

### test_config_has_required_fields
**Purpose:** Verify device configuration contains all required fields.

**Steps:**
1. Load device configuration from YAML
2. Check for required fields: ip, username, password, model, platform
3. Assert all fields are present

**Expected Results:**
```yaml
ip: "192.168.1.246"
username: "admin"
password: "admin123"
model: "X300"
platform: "STM32MP1"
ssh_port: 6022
```

**Pass Criteria:**
- All required fields present in config
- No missing keys

---

### test_device_is_stm32mp1
**Purpose:** Verify device is STM32MP1-based platform.

**Steps:**
1. Load device configuration
2. Check platform field
3. Check model is in supported list

**Expected Results:**
- `platform: "STM32MP1"`
- `model` in ['X300', 'XLR', 'BTIO', 'AUD_USB', 'AUD_IO', 'POE_SPK']

**Pass Criteria:**
- Platform is STM32MP1
- Model is supported

---

## DSP Mode Tests

### test_get_current_mode
**Purpose:** Read current DSP operating mode from device.

**Steps:**
1. Connect to device via SSH
2. Execute: `dsp_test mode`
3. Parse output to determine mode

**Expected Results:**
```
DSP mode is  Residential
```
or
```
DSP mode is  Commercial
```

**Pass Criteria:**
- Command executes successfully
- Output contains "Residential" or "Commercial"
- Controller returns 'residential' or 'commercial'

---

### test_get_zone_count
**Purpose:** Verify zone count matches current DSP mode.

**Steps:**
1. Connect to device
2. Get current mode: `dsp_test mode`
3. Get zone count via controller
4. Verify count matches mode

**Expected Results:**

**Residential Mode:**
- Zone count: 2
- Each zone has stereo (L/R) channels

**Commercial Mode:**
- Channel count: 4
- Each channel is mono

**Pass Criteria:**
- Residential mode → 2 zones
- Commercial mode → 4 channels
- Count matches mode configuration

---

### test_set_mode
**Purpose:** Verify DSP mode can be switched between residential and commercial.

**Test runs twice:** Once for residential, once for commercial (pytest.parametrize)

#### Setting Residential Mode:

**Steps:**
1. Read initial mode: `dsp_test mode`
2. Set to residential: `dsp_test mode 0`
3. Verify mode changed: `dsp_test mode` → "Residential"
4. Restore initial mode

**Expected Results:**
```
Set DSP mode to Residential
```

#### Setting Commercial Mode:

**Steps:**
1. Read initial mode: `dsp_test mode`
2. Set to commercial: `dsp_test mode 1`
3. Verify mode changed: `dsp_test mode` → "Commercial"
4. Restore initial mode

**Expected Results:**
```
Set DSP mode to Commercial
```

**Pass Criteria:**
- Mode switches successfully
- Verification confirms new mode
- Initial mode restored after test

**Important Notes:**
- Mode switching may affect active audio routing
- Zone count changes with mode (2 vs 4)
- Always restore initial mode to avoid affecting other tests

---

## Amplifier Control Tests

**HARDWARE LIMITATION:** X300 amplifiers can only be enabled/disabled by **zone pairs**, not individual channels:
- **Amp Zone 1:** Controls output channels 0-1
- **Amp Zone 2:** Controls output channels 2-3

### test_get_amp_zone_status
**Purpose:** Read current amplifier zone enable status.

**Steps:**
1. Connect to device
2. Read zone 1 status: `cat /sys/class/leds/AMP_ENABLE_Z1/brightness`
3. Read zone 2 status: `cat /sys/class/leds/AMP_ENABLE_Z2/brightness`
4. Display status (0=disabled, 1=enabled)

**Expected Results:**
```
Amplifier Zone Status:
  Zone 1 (ch 0-1): ENABLED
  Zone 2 (ch 2-3): ENABLED
```

**Pass Criteria:**
- Both status reads return 0 or 1
- Values are boolean (True/False)

---

### test_enable_disable_amp_zone
**Purpose:** Verify amplifier zones can be enabled and disabled independently.

#### Zone 1 Testing:

**Steps:**
1. Read initial zone 1 state
2. Enable zone 1: `echo 1 > /sys/class/leds/AMP_ENABLE_Z1/brightness`
3. Verify enabled: `cat /sys/class/leds/AMP_ENABLE_Z1/brightness` → "1"
4. Disable zone 1: `echo 0 > /sys/class/leds/AMP_ENABLE_Z1/brightness`
5. Verify disabled: `cat /sys/class/leds/AMP_ENABLE_Z1/brightness` → "0"

**Expected Results:**
- Zone 1 enables successfully
- Zone 1 disables successfully
- Status readback matches set value

#### Zone 2 Testing:

**Steps:**
1. Read initial zone 2 state
2. Enable zone 2: `echo 1 > /sys/class/leds/AMP_ENABLE_Z2/brightness`
3. Verify enabled: `cat /sys/class/leds/AMP_ENABLE_Z2/brightness` → "1"
4. Disable zone 2: `echo 0 > /sys/class/leds/AMP_ENABLE_Z2/brightness`
5. Verify disabled: `cat /sys/class/leds/AMP_ENABLE_Z2/brightness` → "0"

**Expected Results:**
- Zone 2 enables successfully
- Zone 2 disables successfully
- Status readback matches set value

**Restoration:**
- Both zones restored to initial state after test

**Mode Dependency:**

**Residential Mode (2 stereo zones):**
- Amp Zone 1 controls Audio Zone 1 (stereo L/R)
- Amp Zone 2 controls Audio Zone 2 (stereo L/R)
- 1:1 mapping between amp zones and audio zones

**Commercial Mode (4 mono channels):**
- Amp Zone 1 controls Channels 1 & 2 (outputs 0-1)
  - **Cannot enable Channel 1 without Channel 2**
- Amp Zone 2 controls Channels 3 & 4 (outputs 2-3)
  - **Cannot enable Channel 3 without Channel 4**
- Granularity limited to amp zone pairs

**Pass Criteria:**
- All enable commands succeed
- All disable commands succeed
- Status readback accurate
- Initial state restored

---

### test_amp_always_on
**Purpose:** Verify amplifier always-on mode can be enabled/disabled.

**Always-On Mode:** When enabled, amplifiers stay powered on regardless of signal presence. When disabled, amps follow signal sense or manual control.

**Steps:**
1. Read initial always-on state: `cat /sys/class/leds/AMP_ALWAYS_ON/brightness`
2. Enable always-on: `echo 1 > /sys/class/leds/AMP_ALWAYS_ON/brightness`
3. Verify enabled: `cat /sys/class/leds/AMP_ALWAYS_ON/brightness` → "1"
4. Disable always-on: `echo 0 > /sys/class/leds/AMP_ALWAYS_ON/brightness`
5. Verify disabled: `cat /sys/class/leds/AMP_ALWAYS_ON/brightness` → "0"
6. Restore initial state

**Expected Results:**
- Enable: always-on set to 1 (amps stay on)
- Disable: always-on set to 0 (amps follow control logic)
- Readback matches set value

**Behavior:**
- **Enabled:** Amps remain powered regardless of signal presence or zone enable
- **Disabled:** Amps follow signal sense and/or zone enable settings

**Pass Criteria:**
- Always-on toggles correctly
- Status readback accurate
- Initial state restored

---

### test_signal_sense
**Purpose:** Verify signal sense mode can be enabled/disabled.

**Signal Sense Mode:** When enabled, amplifiers automatically turn on when audio signal is detected on inputs. When disabled, amps must be manually controlled.

**Steps:**
1. Read initial signal sense state: `cat /sys/class/leds/AMP_SIGNAL_SENSE/brightness`
2. Enable signal sense: `echo 1 > /sys/class/leds/AMP_SIGNAL_SENSE/brightness`
3. Verify enabled: `cat /sys/class/leds/AMP_SIGNAL_SENSE/brightness` → "1"
4. Disable signal sense: `echo 0 > /sys/class/leds/AMP_SIGNAL_SENSE/brightness`
5. Verify disabled: `cat /sys/class/leds/AMP_SIGNAL_SENSE/brightness` → "0"
6. Restore initial state

**Expected Results:**
- Enable: signal sense set to 1 (auto-on with signal)
- Disable: signal sense set to 0 (manual control only)
- Readback matches set value

**Behavior:**
- **Enabled:** Amps auto-enable when audio signal detected
- **Disabled:** Amps require manual enable via zone control

**Pass Criteria:**
- Signal sense toggles correctly
- Status readback accurate
- Initial state restored

---

## Back Panel Switch Tests

**File:** `test_basic_connectivity.py`  
**Category:** TestBackPanelSwitches

### Background
The X300 has 4 physical DIP switches on the back panel that control hardware configuration. These switches can be read (but not controlled) via sysfs GPIO interface. They are read-only - they reflect the physical switch positions.

**Switch Types:**
1. **Power Mode Switch** - Power Saver vs Always On
2. **Impedance Switch** - LoZ vs 70V/100V
3. **Zone 1 Mode Switch** - Ch 1-2: Stereo vs Bridge/Sum
4. **Zone 2 Mode Switch** - Ch 3-4: Stereo vs Bridge/Sum

**Availability:**
- **All X300 models:** All 4 switches available

**sysfs Paths:**
```
/sys/class/leds/AMP_ALWAYS_ON/brightness  # Power mode
/sys/class/leds/AMP_H_Z/brightness        # Impedance
/sys/class/leds/AMP_Z1_SE/brightness      # Zone 1 mode
/sys/class/leds/AMP_Z2_SE/brightness      # Zone 2 mode
```

### test_read_power_mode_switch
**Purpose:** Read power mode switch position from back panel.

**Switch Position:**
- **0:** Power Saver mode
- **1:** Always On mode

**Steps:**
1. Connect to device via SSH (port 6022)
2. Read power mode switch:
   ```bash
   cat /sys/class/leds/AMP_ALWAYS_ON/brightness
   ```
3. Parse output (0 or 1)
4. Display power mode

**Expected Results:**
```
Power Mode Switch: Always On (1)
✓ Power mode switch read successfully
```
or
```
Power Mode Switch: Power Saver (0)
✓ Power mode switch read successfully
```

**Pass Criteria:**
- Switch read successfully  
- Returns 0 or 1
- No errors accessing sysfs

**Note:** This is a **read-only** physical switch. The test verifies it can be read, not controlled.

---

### test_read_impedance_switch
**Purpose:** Read impedance switch position from back panel.

**Switch Position:**
- **0:** LoZ (Low Impedance) mode
- **1:** 70V/100V (High Impedance) mode

**Steps:**
1. Connect to device via SSH (port 6022)
2. Read impedance switch:
   ```bash
   cat /sys/class/leds/AMP_H_Z/brightness
   ```
3. Parse output (0 or 1)
4. Display impedance mode

**Expected Results:**
```
Impedance Switch: LoZ (0)
✓ Impedance switch read successfully
```
or
```
Impedance Switch: 70V/100V (1)
✓ Impedance switch read successfully
```

**Pass Criteria:**
- Switch read successfully
- Returns 0 or 1
- No errors accessing sysfs

---

### test_read_zone1_mode_switch
**Purpose:** Read Zone 1 (Ch 1-2) mode switch position from back panel.

**Switch Position:**
- **0:** Bridge/Sum mode
- **1:** Stereo mode

**Steps:**
1. Connect to device via SSH (port 6022)
2. Read Zone 1 mode switch:
   ```bash
   cat /sys/class/leds/AMP_Z1_SE/brightness
   ```
3. Parse output (0 or 1)
4. Display zone mode

**Expected Results:**
```
Zone 1 Mode Switch (Ch 1-2): Stereo (1)
✓ Zone 1 mode switch read successfully
```
or
```
Zone 1 Mode Switch (Ch 1-2): Bridge/Sum (0)
✓ Zone 1 mode switch read successfully
```

**Pass Criteria:**
- Switch read successfully
- Returns 0 or 1
- No errors accessing sysfs

---

### test_read_zone2_mode_switch
**Purpose:** Read Zone 2 (Ch 3-4) mode switch position from back panel.

**Switch Position:**
- **0:** Bridge/Sum mode
- **1:** Stereo mode

**Steps:**
1. Connect to device via SSH (port 6022)
2. Read Zone 2 mode switch:
   ```bash
   cat /sys/class/leds/AMP_Z2_SE/brightness
   ```
3. Parse output (0 or 1)
4. Display zone mode

**Expected Results:**
```
Zone 2 Mode Switch (Ch 3-4): Stereo (1)
✓ Zone 2 mode switch read successfully
```
or
```
Zone 2 Mode Switch (Ch 3-4): Bridge/Sum (0)
✓ Zone 2 mode switch read successfully
```

**Pass Criteria:**
- Switch read successfully
- Returns 0 or 1
- No errors accessing sysfs

---

### test_read_all_switches
**Purpose:** Read all back panel switch positions at once.

**Steps:**
1. Connect to device via SSH (port 6022)
2. Read all 4 switches:
   - Power mode
   - Impedance
   - Zone 1 mode
   - Zone 2 mode
3. Display all switch positions

**Expected Results:**
```
All Back Panel Switches:
  Power Mode:      Always On (1)
  Impedance:       LoZ (0)
  Zone 1 (Ch 1-2): Stereo (1)
  Zone 2 (Ch 3-4): Bridge/Sum (0)
✓ All back panel switches read successfully
```

**Pass Criteria:**
- All 4 switches read successfully
- Each switch returns 0 or 1
- Dictionary contains all required keys
- No errors accessing sysfs

---

## Test Execution

### Run All Tests
```bash
cd DM-NAX-X300_test_suite
./run_tests.sh
```

### Run Back Panel Switch Tests Only
```bash
# All back panel switch tests
pytest tests/test_basic_connectivity.py::TestBackPanelSwitches -v

# T2P switch only
pytest tests/test_basic_connectivity.py::TestBackPanelSwitches::test_read_t2p_switch -v

# All speaker switches
pytest tests/test_basic_connectivity.py::TestBackPanelSwitches::test_read_speaker_switches -v

# Individual speaker switch (channel 1)
pytest tests/test_basic_connectivity.py::TestBackPanelSwitches::test_read_individual_speaker_switch[1] -v
```

### Python API Usage
```python
from lib.x300_controller import X300Controller

config = {
    'ip': '192.168.1.246',
    'username': 'admin',
    'password': 'admin123',
    'model': 'X300',
    'platform': 'STM32MP1',
    'ssh_port': 6022
}

with X300Controller(config) as controller:
    # Read T2P switch
    t2p_enabled = controller.get_t2p_switch()
    power_mode = "25W" if t2p_enabled else "13W"
    print(f"Power mode: {power_mode}")
    
    # Read individual speaker switch
    spk1_ext = controller.get_speaker_switch(1)
    position = "EXT" if spk1_ext else "SPK"
    print(f"SPK1: {position}")
    
    # Read all speaker switches
    switches = controller.get_all_speaker_switches()
    for channel, state in switches.items():
        if state is not None:
            position = "EXT" if state else "SPK"
            print(f"SPK{channel}: {position}")
```

---

## Troubleshooting

### SSH Connection Fails
**Check:**
- Device IP address: 192.168.1.246
- SSH port: 6022 (not 22!)
- Credentials: admin/admin123
- Network connectivity: `ping 192.168.1.246`

### DSP Commands Return "Command not found"
**Check:**
- Using correct command: `dsp_test` (not `dsp`)
- DSP is started: `dsp_test start`
- Firmware version supports command

### Mode Switch Doesn't Take Effect
**Try:**
- Restart DSP: `dsp_test start`
- Check mode with: `dsp_test mode`
- Verify in status table: `dsp_test` (look for [Mode:RESI] or [Mode:COMM])

### Amp Zone Control No Effect
**Check:**
- Zone number is 1 or 2 (not 0-3)
- Using correct sysfs path: `/sys/class/leds/AMP_ENABLE_Z{zone}/brightness`
- Writing 0 or 1 (not other values)
- Check if always-on mode is enabled (overrides zone control)

### Back Panel Switch Read Fails
**Check:**
- Using correct sysfs paths:
  - T2P: `/sys/crestron/ctrl-back-panel/switches/switch_t2p`
  - Speaker: `/sys/crestron/ctrl-back-panel/switches/switch_spk_{1-12}`
- SSH connection on port 6022 (not 22)
- Admin privileges (default admin user should have access)

**Verify sysfs available:**
```bash
ssh -p 6022 admin@192.168.1.246
ls -la /sys/crestron/ctrl-back-panel/switches/
```

**Expected output:**
```
switch_spk_1
switch_spk_2
...
switch_spk_12
switch_t2p
```

**Note:** These switches are read-only - you cannot write to them. They reflect physical hardware switch positions on the device back panel.

### Speaker Switch Returns "Not Available"
**This is normal** - not all X300 models have all 12 speaker outputs. The test handles this gracefully by:
- Reporting `None` for unavailable switches
- Skipping tests for unavailable channels
- Verifying at least one switch is readable

**Models with fewer outputs:**
- X300 may have 4, 8, or 12 outputs depending on configuration
- POE-SPKR models may have fewer channels

---

## See Also

- [README.md](../README.md) - Getting started guide
- [DSP_MODES.md](DSP_MODES.md) - Residential vs Commercial mode details
- [ARCHITECTURE.md](ARCHITECTURE.md) - X300 hardware architecture
- [QUICK_START.md](QUICK_START.md) - Quick start guide
