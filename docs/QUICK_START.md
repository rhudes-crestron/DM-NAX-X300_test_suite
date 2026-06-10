# Quick Start Guide - DM-NAX-X300 Test Suite

## Initial Setup

```bash
cd /home/rhudes/Linux_jstr1000/DM-NAX-X300_test_suite

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Test Your Connection

**The test suite will prompt you for device IP, username, and password:**

```bash
# Run basic connectivity test
./run_tests.sh
```

You'll see:
```
============================================================
X300 Device Configuration Required
============================================================
Enter device IP [192.168.1.246]: YOUR_X300_IP
Enter username [admin]: 
Enter password [admin123]: 
============================================================
```

Just press **Enter** for username and password to use the defaults (admin/admin123), or type your own values.

## Discover X300 Commands

SSH into your device to explore available commands:

```bash
ssh admin@YOUR_X300_IP

# Try these commands to discover audio control interface:
help
ls /usr/bin/ | grep -i audio
ls /usr/bin/ | grep -i dsp
systemctl list-units | grep -i audio
```

Look for commands similar to:
- Audio routing commands
- Volume control
- DSP state/status queries
- Mixer configuration

## Update Controller Implementation

Once you know the X300 commands, update `lib/x300_controller.py`:

```python
def route_audio(self, input_name: str, output_name: str):
    """Route audio input to output."""
    # Replace with actual X300 command
    cmd = f"your_x300_route_command {input_name} {output_name}"
    return self.run_command(cmd)
```

## Run Tests

```bash
# Run all tests (will prompt for IP/username/password)
./run_tests.sh

# Run quick subset (will also prompt)
./run_tests.sh --quick

# Skip prompts and use config file
./run_tests.sh --skip-prompt

# Use environment variables (no prompt)
X300_IP=192.168.1.246 X300_USERNAME=admin X300_PASSWORD=admin123 ./run_tests.sh
```

## Merge Work from feature/x300 Branch

If the feature/x300 branch has X300 implementation details:

```bash
# Add remote if not already added
git remote add upstream https://nj-github.crestron.crestron.com/CrestronEngineering/DM-NAX_test_suite.git

# Fetch the feature branch
git fetch upstream feature/x300

# View what's in the branch
git log upstream/feature/x300

# Merge or cherry-pick specific commits
git merge upstream/feature/x300
# OR
git cherry-pick <commit-hash>
```

## Next Steps

1. ✓ Test suite structure created
2. ☐ Configure X300 device IP
3. ☐ Test SSH connectivity
4. ☐ Discover X300 audio commands
5. ☐ Implement X300Controller methods
6. ☐ Port tests from FPGA suite
7. ☐ Add X300-specific tests

## Troubleshooting

### SSH Connection Fails

```bash
# Check if device is reachable
ping YOUR_X300_IP

# Try manual SSH
ssh admin@YOUR_X300_IP

# Check SSH port (default 22)
nmap -p 22 YOUR_X300_IP
```

### Module Import Errors

```bash
# Make sure virtual environment is activated
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

### Tests Skip with "Not Implemented"

This is expected! The X300-specific commands need to be implemented in `lib/x300_controller.py` first.

## Resources

- **FPGA Test Suite** (for reference): `/home/rhudes/Linux_jstr1000/DM-NAX_test_suite/`
- **X300 Build Script**: `/home/rhudes/Linux_jstr1000/build-x300-dunfell.sh`
- **Architecture Docs**: `docs/ARCHITECTURE.md`
- **Feature Branch**: https://nj-github.crestron.crestron.com/CrestronEngineering/DM-NAX_test_suite.git (feature/x300)
