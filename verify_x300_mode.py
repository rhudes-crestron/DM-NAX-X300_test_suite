#!/usr/bin/env python3
"""
X300 Mode Verification

Verifies the residential/commercial mode on X300 devices using dsp_test command.

X300 uses different commands than 8ZSA/FPGA devices:
  - Uses: dsp_test mode (works via SSH)
  - Does NOT have: ampctrl command

Usage:
    export X300_IP=192.168.1.246 X300_USERNAME=admin X300_PASSWORD=admin123
    python3 verify_x300_mode.py
"""
import sys
import os
sys.path.insert(0, 'lib')

from x300_controller import X300Controller

# Get connection info from environment
X300_IP = os.environ.get('X300_IP', '192.168.1.246')
X300_USERNAME = os.environ.get('X300_USERNAME', 'admin')
X300_PASSWORD = os.environ.get('X300_PASSWORD', 'admin123')
X300_PORT = int(os.environ.get('X300_PORT', '6022'))

def main():
    print("=" * 70)
    print("X300 Residential/Commercial Mode Verification")
    print("=" * 70)
    print(f"\nConnecting to {X300_IP}:{X300_PORT}...")
    
    config = {
        'ip': X300_IP,
        'username': X300_USERNAME,
        'password': X300_PASSWORD,
        'ssh_port': X300_PORT,
        'model': 'X300'
    }
    
    controller = X300Controller(config)
    
    try:
        controller.connect()
        print("✓ Connected successfully\n")
        
        # Get mode using dsp_test (works via SSH on X300)
        print("=" * 70)
        print("Mode Verification (using dsp_test)")
        print("=" * 70)
        print("Command: dsp_test mode")
        print("\nThis reads the DSP operating mode:")
        print("  - Residential: 2 stereo zones")
        print("  - Commercial: 4 mono channels")
        
        mode = controller.get_mode()
        zones = controller.get_zone_count()
        
        print(f"\nCurrent Mode: {mode.upper()}")
        print(f"Zone Count: {zones}")
        
        # Show configuration details
        print("\n" + "=" * 70)
        print("Current Configuration")
        print("=" * 70)
        
        print(f"\nCurrent Mode: {mode.upper()}")
        if mode == 'residential':
            print("\nRESIDENTIAL MODE:")
            print("  - 2 Stereo Zones")
            print("  - 4 Output channels: Z1L, Z1R, Z2L, Z2R")
            print("  - Typical use: Home theater / consumer applications")
        else:
            print("\nCOMMERCIAL MODE:")
            print("  - 4 Mono Channels")
            print("  - 4 Output channels: CH1, CH2, CH3, CH4")
            print("  - Typical use: Distributed audio / commercial installations")
        
        # Show how to change mode
        print("\n" + "=" * 70)
        print("Changing Modes")
        print("=" * 70)
        
        other_mode = 'commercial' if mode == 'residential' else 'residential'
        
        print(f"\nTo switch to {other_mode.upper()} mode:")
        print(f"\n  RECOMMENDED METHOD (from device console):")
        print(f"  1. Connect to device console (serial or web interface)")
        print(f"  2. At DM-NAX-AMP-X300> prompt, run:")
        print(f"     aconfigcontrol set{'comme' if other_mode == 'commercial' else 'resid'}boot")
        print(f"  3. Reboot device for change to take effect")
        print(f"  4. Verify with: dsp_test mode")
        print(f"\n  Why use aconfigcontrol?")
        print(f"    - Synchronizes ALL components (DSP, AMP control, etc.)")
        print(f"    - Ensures system-wide consistency")
        print(f"    - Prevents component mismatches")
        print(f"\n  Note: aconfigcontrol is console-only and NOT available via SSH")
        
        print("\n" + "=" * 70)
        print("✓ Mode verification complete")
        print("=" * 70)
        
        controller.disconnect()
        
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
