# DM-NAX-X300 Architecture & Differences

## Platform Overview

The X300 series uses **STM32MP1** (ARM Cortex-A7 + Cortex-M4) processors, fundamentally different from the FPGA-based DM-NAX devices.

### Hardware Comparison

| Aspect | FPGA Devices (8ZSA/4ZSA/4ZSP) | STM32MP1 Devices (X300) |
|--------|------------------------------|-------------------------|
| **Primary Processor** | Altera Cyclone V FPGA | STMicroelectronics STM32MP157C |
| **DSP** | Analog Devices SHARC ADSP-21489 | ARM Cortex-M4 coprocessor |
| **Architecture** | FPGA fabric + external DSP | Dual-core ARM + MCU |
| **Audio Processing** | Hardware DSP blocks | Software DSP / firmware |
| **Firmware Type** | fw21/fw42 DSP firmware | Linux-based (Yocto/Dunfell) |
| **Boot Loader** | U-Boot for Altera SOCFPGA | U-Boot for STM32MP1 |
| **Build System** | `build-dmnax-intel.sh` | `build-x300-dunfell.sh` |

## Test Suite Differences

### Why Separate Test Suites?

1. **Different command interfaces**: FPGA devices use `dsp tone`, `dsp mix` commands; X300 uses different APIs
2. **Different firmware architecture**: No SHARC DSP blocks on X300
3. **Different audio paths**: X300 processing done in software on ARM core
4. **Different capabilities**: X300 may have different zone counts, I/O types
5. **Different update mechanisms**: FPGA uses `.puf` files; X300 may use different format

### Command Translations (TBD)

These are **placeholders** until actual X300 command structure is known:

| Function | FPGA Command | X300 Command (TBD) |
|----------|-------------|-------------------|
| Tone generation | `dsp tone <ch> <freq> <gain>` | *Needs investigation* |
| DSP state read | `dsp` | *Needs investigation* |
| Mixer crosspoint | `dsp mix <in> <out> <gain>` | *Needs investigation* |
| Routing | CresNext `/AvMatrixRouting/` | *May be similar or different* |

## Development Roadmap

To complete X300 test support:

1. **Investigate actual X300 SSH commands**
   - Audio routing commands
   - Volume/mute control
   - Signal measurement methods
   - Firmware query commands

2. **Test CresNext API compatibility**
   - Does X300 use same REST API as FPGA devices?
   - Are `/Device/ZoneOutputs/` paths the same?
   - Authentication mechanism (XSRF tokens?)

3. **Implement X300Controller methods**
   - Audio routing
   - Volume control
   - Signal measurement
   - Device info queries

4. **Port relevant tests from FPGA suite**
   - Volume control tests
   - Mute tests
   - Routing tests
   - Streaming tests (if applicable)

5. **Add X300-specific tests**
   - GPIO tests (if applicable)
   - Power management (PoE devices)
   - USB audio (AUD-USB)
   - Bluetooth (BTIO)

## Getting Started

### Merge from feature/x300 Branch

The feature/x300 branch has work-in-progress X300 support:

```bash
cd DM-NAX-X300_test_suite
git remote add upstream https://nj-github.crestron.crestron.com/CrestronEngineering/DM-NAX_test_suite.git
git fetch upstream feature/x300
git merge upstream/feature/x300
```

### Next Steps

1. Configure your X300 device in `config/devices.yaml`
2. SSH into X300 to discover available commands
3. Update `lib/x300_controller.py` with actual command implementations
4. Enable tests in `tests/` as functionality is added

## References

- Build script: `/home/rhudes/Linux_jstr1000/build-x300-dunfell.sh`
- Custom STM32 files: `/home/rhudes/Linux_jstr1000/customFiles_stm/stm32mp1/`
- Device tree: `customFiles_stm/stm32mp1/bsp/u-boot-stm32mp1/arch/arm/dts/crestron-gemini-hub-rev-a.dts`
- Feature branch: https://nj-github.crestron.crestron.com/CrestronEngineering/DM-NAX_test_suite.git (feature/x300)
