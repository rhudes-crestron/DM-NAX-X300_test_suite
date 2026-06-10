#!/usr/bin/env python3
"""
Quick test script to verify X300 connection
"""
import sys
import yaml
from lib.x300_controller import X300Controller

# Load config
with open('config/devices.yaml') as f:
    config = yaml.safe_load(f)['devices']['DM-NAX-X300-001']

print(f"Testing connection to X300 at {config['ip']}...")
print("=" * 60)

try:
    # Connect and get device info
    ctrl = X300Controller(config)
    print(f"Attempting SSH connection as {config['username']}@{config['ip']}...")
    ctrl.connect()
    print("✓ SSH connection successful\n")
    
    try:
        
        # Get device info
        print("Device Information:")
        info = ctrl.get_device_info()
        for key, value in info.items():
            print(f"  {key}: {value}")
        
        print("\nTesting DSP commands...")
        
        # Start DSP processing (required on X300)
        print("\n1. Starting DSP audio processing...")
        ctrl.start_dsp()
        print("   ✓ DSP started")
        
        # Test dsp command
        print("\n2. Reading DSP state...")
        dsp_output = ctrl.read_dsp_state()
        print(f"   DSP output (first 300 chars):\n{dsp_output[:300]}")
        
        # Test tone generation
        print("\n3. Starting 1kHz test tone on channel 0...")
        ctrl.start_tone(0, 1000, -20)
        print("   ✓ Tone started (dsp_test tone 0 1000 -20)")
        
        print("\n4. Stopping tone...")
        ctrl.stop_tone(0)
        print("   ✓ Tone stopped")
        
        print("\n" + "=" * 60)
        print("✓ All tests passed! X300 is ready.")
        
    finally:
        ctrl.disconnect()
        
except Exception as e:
    print(f"\n✗ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
