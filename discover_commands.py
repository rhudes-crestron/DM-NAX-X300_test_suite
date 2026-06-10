#!/usr/bin/env python3
"""
X300 Command Discovery Script
Connects to X300 and discovers available audio/DSP commands
"""
import sys
import yaml
from lib.x300_controller import X300Controller

# Load config
with open('config/devices.yaml') as f:
    config = yaml.safe_load(f)['devices']['DM-NAX-X300-001']

print(f"Connecting to X300 at {config['ip']}...")
print("=" * 70)

try:
    ctrl = X300Controller(config)
    ctrl.connect()
    print("✓ SSH connection successful\n")
    
    # Discovery commands
    discovery_cmds = [
        ("Check for 'dsp' command", "which dsp || echo 'dsp not found'"),
        ("Check for 'help'", "help 2>&1 | head -20"),
        ("Search /usr/bin for audio", "ls /usr/bin/ | grep -iE '(audio|dsp|tone|mix|sound)'"),
        ("Search /usr/sbin for audio", "ls /usr/sbin/ | grep -iE '(audio|dsp|tone|mix|sound)'"),
        ("Check for crestron binary", "which crestron || ls /usr/bin/crest* 2>/dev/null || echo 'none found'"),
        ("Running audio processes", "ps aux | grep -iE '(audio|dsp|alsa|pulse)' | grep -v grep | head -10"),
        ("Check systemd services", "systemctl list-units | grep -iE '(audio|sound)' || echo 'none found'"),
        ("List first 30 binaries", "ls /usr/bin/ | head -30"),
    ]
    
    for title, cmd in discovery_cmds:
        print(f"\n{'─' * 70}")
        print(f"▶ {title}")
        print(f"  Command: {cmd}")
        print(f"{'─' * 70}")
        try:
            output = ctrl.run_command(cmd, timeout=10)
            if output.strip():
                print(output)
            else:
                print("  (no output)")
        except Exception as e:
            print(f"  Error: {e}")
    
    ctrl.disconnect()
    print("\n" + "=" * 70)
    print("Discovery complete.")
    
except Exception as e:
    print(f"\n✗ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
