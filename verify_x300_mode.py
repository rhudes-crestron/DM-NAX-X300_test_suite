#!/usr/bin/env python3
"""
X300 Mode Verification - Using both AConfigControl and ampctrl

This script demonstrates how to verify the residential/commercial mode
using two different commands:
  1. AConfigControl - Shows saved and running mode (from config)
  2. ampctrl - Shows actual running mode (from registers read at boot)

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
        
        # Method 1: AConfigControl (shows saved and running modes)
        print("=" * 70)
        print("Method 1: AConfigControl (Config-based)")
        print("=" * 70)
        print("Command: AConfigControl")
        print("\nThis shows:")
        print("  - Saved mode (what will be used after next reboot)")
        print("  - Running mode (what DSP is currently using)")
        
        mode_details = controller.get_mode_detailed()
        print(f"\nAoIP Mode:")
        print(f"  Saved:   {mode_details.get('aoip_saved', 'Unknown')}")
        print(f"  Running: {mode_details.get('aoip_running', 'Unknown')}")
        print(f"\nAudio Mode:")
        print(f"  Saved:   {mode_details.get('audio_saved', 'Unknown').title()}")
        print(f"  Running: {mode_details.get('audio_running', 'Unknown').title()}")
        
        # Method 2: ampctrl (shows actual running mode)
        print("\n" + "=" * 70)
        print("Method 2: ampctrl (Register-based)")
        print("=" * 70)
        print("Command: ampctrl")
        print("\nThis shows:")
        print("  - Actual mode that AMP control application is using")
        print("  - Read from hardware registers at boot time")
        print("  - Also shows power mode (Always On vs Power Saver)")
        
        ampctrl_mode = controller.get_ampctrl_mode_from_status()
        print(f"\nAudio Mode: {ampctrl_mode.get('audio_mode', 'Unknown').title()}")
        print(f"Power Mode: {ampctrl_mode.get('power_mode', 'Unknown').replace('_', ' ').title()}")
        
        # Verify consistency
        print("\n" + "=" * 70)
        print("Mode Consistency Check")
        print("=" * 70)
        
        consistency = controller.verify_mode_consistency()
        
        print(f"\nAConfigControl Saved:    {consistency['aconfig_saved'].title()}")
        print(f"AConfigControl Running:  {consistency['aconfig_running'].title()}")
        print(f"ampctrl Running:         {consistency['ampctrl_running'].title()}")
        print(f"\nAll modes consistent: {'✓ YES' if consistency['consistent'] else '✗ NO'}")
        print(f"Reboot needed:        {'✓ YES' if consistency['needs_reboot'] else '✗ NO'}")
        
        if not consistency['consistent']:
            print("\n⚠ WARNING: Modes are inconsistent!")
            if consistency['needs_reboot']:
                print("  → Saved mode differs from running mode")
                print(f"  → Device will switch to {consistency['aconfig_saved'].upper()} after reboot")
            else:
                print("  → This may indicate a configuration issue")
        else:
            print(f"\n✓ Device is properly configured in {consistency['aconfig_running'].upper()} mode")
        
        # Show what each mode means
        print("\n" + "=" * 70)
        print("Mode Descriptions")
        print("=" * 70)
        current_mode = consistency['ampctrl_running']
        if current_mode == 'residential':
            print("\nRESIDENTIAL MODE (Current):")
            print("  - 2 Stereo Zones")
            print("  - 4 Output channels: Z1L, Z1R, Z2L, Z2R")
            print("  - Typical use: Home theater / consumer applications")
        else:
            print("\nCOMMERCIAL MODE (Current):")
            print("  - 4 Mono Channels")
            print("  - 4 Output channels: CH1, CH2, CH3, CH4")
            print("  - Typical use: Distributed audio / commercial installations")
        
        other_mode = 'commercial' if current_mode == 'residential' else 'residential'
        print(f"\nTo switch to {other_mode.upper()} mode:")
        print(f"  1. Run: AConfigControl set{'resid' if other_mode == 'residential' else 'comme'}boot")
        print(f"  2. Reboot device")
        print(f"  3. Verify with this script")
        
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
