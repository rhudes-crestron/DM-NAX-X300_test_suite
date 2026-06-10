# Device Configuration for Testing

**By default, the X300 test suite will prompt you for device IP, username, and password when you run it.**

This makes it easy to test different devices without editing config files.

## How It Works

When you run the test suite, you'll see:

```
============================================================
X300 Device Configuration Required
============================================================
Enter device IP [192.168.1.246]: 
Enter username [admin]: 
Enter password [admin123]: 
============================================================
```

- Type the IP address and press Enter (or just press Enter to use the default from config)
- Type the username and press Enter (or just press Enter to use `admin`)
- Type the password (hidden for security) and press Enter (or just press Enter to use `admin123`)
- Tests will run with those settings

## Override Options

### Method 1: Interactive Prompt (Default - Recommended)

Just run the tests - you'll be prompted:

```bash
./run_tests.sh              # Will prompt for IP, username, password
pytest -v                   # Will also prompt
```

### Method 2: Environment Variables (No Prompt)

Set environment variables to skip the prompt:

```bash
export X300_IP=192.168.1.246
export X300_USERNAME=admin
export X300_PASSWORD=admin123
./run_tests.sh
```

Or in one line:
```bash
X300_IP=192.168.1.246 X300_USERNAME=admin X300_PASSWORD=admin123 ./run_tests.sh
```

### Method 3: Config File + Skip Prompt

Edit `config/devices.yaml` and use `--skip-prompt`:

```bash
./run_tests.sh --skip-prompt
```

Or with pytest:
```bash
pytest -v --skip-prompt
```

## Priority Order

Configuration values are applied in this order (later overrides earlier):

1. Config file (`config/devices.yaml`)
2. Environment variables (`X300_IP`, `X300_USERNAME`, `X300_PASSWORD`)
3. Interactive prompt (if environment variables not set)

Use `--skip-prompt` to disable the interactive prompt and only use config/environment.

## Examples

### Normal usage (default - will prompt for IP/username/password):
```bash
./run_tests.sh
```

### Skip prompt and use config file:
```bash
./run_tests.sh --skip-prompt
```

### Use environment variables (no prompt):
```bash
X300_IP=192.168.1.100 X300_USERNAME=root X300_PASSWORD=rootpass ./run_tests.sh
```

### Quick test with prompt:
```bash
./run_tests.sh --quick
```

### Quick test with environment variables:
```bash
export X300_IP=192.168.1.246
export X300_USERNAME=admin
export X300_PASSWORD=admin123
./run_tests.sh --quick
```

### Test specific device (will prompt):
```bash
./run_tests.sh --device X300-001
```

## Testing Multiple Devices

To test multiple devices at different IPs, just run the test suite multiple times.
You'll be prompted for configuration each time:

```bash
# Device 1
./run_tests.sh
# (Enter IP: 192.168.1.100, username: admin, password: pass1)

# Device 2  
./run_tests.sh
# (Enter IP: 192.168.1.101, username: admin, password: pass2)

# Device 3
./run_tests.sh
# (Enter IP: 192.168.1.102, username: root, password: pass3)
```

Or use environment variables for automation:

```bash
X300_IP=192.168.1.100 X300_USERNAME=admin X300_PASSWORD=pass1 ./run_tests.sh
X300_IP=192.168.1.101 X300_USERNAME=admin X300_PASSWORD=pass2 ./run_tests.sh
X300_IP=192.168.1.102 X300_USERNAME=root X300_PASSWORD=pass3 ./run_tests.sh
```

## Security Notes

⚠️ **Password Security:**

- Passwords are **not echoed** to the screen when typing (hidden input)
- Passwords are only stored in memory during test execution
- **Do not commit real passwords** to git in `config/devices.yaml`
- Use environment variables for CI/CD pipelines
- Use interactive prompts for manual testing
- Keep `config/devices.yaml` with placeholder passwords

## CI/CD Usage

For automated testing in CI/CD pipelines:

```yaml
# Example GitHub Actions
env:
  X300_IP: ${{ secrets.X300_IP }}
  X300_USERNAME: ${{ secrets.X300_USERNAME }}
  X300_PASSWORD: ${{ secrets.X300_PASSWORD }}
run: |
  cd DM-NAX-X300_test_suite
  ./run_tests.sh
```

Or use `--skip-prompt` with configuration in config file:

```bash
./run_tests.sh --skip-prompt
```
