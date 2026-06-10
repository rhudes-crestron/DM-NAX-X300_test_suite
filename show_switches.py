#!/usr/bin/env python3
"""
Utility script to display all X300 back panel switch positions.

Back Panel Switches:
1. Power Mode (Pwr Saver / Always On)
2. Impedance (LoZ / 70V-100V)
3. Zone 1 Mode (Ch 1-2: Stereo / Sum / Bridge)
4. Zone 2 Mode (Ch 3-4: Stereo / Sum / Bridge)

Available on all X300 models.
"""

import os
import sys

# Add lib directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))

from x300_controller import X300Controller


def main():
    """Display all back panel switch positions."""
    # Get connection info from environment or use defaults
    config = {
        'ip': os.environ.get('X300_IP', '192.168.1.246'),
        'username': os.environ.get('X300_USERNAME', 'admin'),
        'password': os.environ.get('X300_PASSWORD', 'admin123'),
        'ssh_port': 6022,
        'model': 'X300'
    }
    
    print("=" * 60)
    print("X300 Back Panel Switch Positions")
    print("=" * 60)
    print(f"Device: {config['ip']}")
    print()
    
    try:
        with X300Controller(config) as controller:
            switches = controller.get_all_back_panel_switches()
            
            print("Switch Positions:")
            print("-" * 60)
            
            # Power Mode (2-position)
            power_mode = switches['power_mode']
            power_str = "Always On" if power_mode == 1 else "Power Saver"
            print(f"1. Power Mode:        {power_str:15} (Value: {power_mode})")
            
            # Impedance (3-position)
            impedance = switches['impedance']
            impedance_map = {1: "LoZ", 2: "100V", 3: "70V"}
            impedance_str = impedance_map.get(impedance, "Unknown")
            print(f"2. Impedance:         {impedance_str:15} (Value: {impedance})")
            
            # Zone 1 Mode (3-position)
            zone1_mode = switches['zone1_mode']
            mode_map = {1: "Stereo", 2: "Bridged", 3: "Sum"}
            zone1_str = mode_map.get(zone1_mode, "Unknown")
            print(f"3. Zone 1 (Ch 1-2):   {zone1_str:15} (Value: {zone1_mode})")
            
            # Zone 2 Mode (3-position)
            zone2_mode = switches['zone2_mode']
            zone2_str = mode_map.get(zone2_mode, "Unknown")
            print(f"4. Zone 2 (Ch 3-4):   {zone2_str:15} (Value: {zone2_mode})")
            
            print("-" * 60)
            print("\nSwitch Value Legend:")
            print("  Power Mode:    0 = Power Saver   | 1 = Always On")
            print("  Impedance:     1 = LoZ           | 2 = 100V        | 3 = 70V")
            print("  Zone Mode:     1 = Stereo        | 2 = Bridged     | 3 = Sum")
            
    except Exception as e:
        print(f"Error reading switches: {e}", file=sys.stderr)
        return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
