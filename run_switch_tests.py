#!/usr/bin/env python3
"""
Standalone test script for X300 back panel switches.
Run without pytest dependency.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))

from x300_controller import X300Controller


def test_power_mode_switch(controller):
    """Test reading power mode switch."""
    print("\nTest: Read Power Mode Switch")
    print("-" * 60)
    
    power_mode = controller.get_power_mode_switch()
    mode_str = "Always On" if power_mode == 1 else "Power Saver"
    print(f"Power Mode Switch: {mode_str} ({power_mode})")
    
    assert power_mode in [0, 1], f"Invalid power mode value: {power_mode}"
    print("✓ PASS: Power mode switch read successfully\n")
    return True


def test_impedance_switch(controller):
    """Test reading impedance switch."""
    print("Test: Read Impedance Switch")
    print("-" * 60)
    
    impedance = controller.get_impedance_switch()
    impedance_map = {1: "LoZ", 2: "100V", 3: "70V"}
    impedance_str = impedance_map.get(impedance, "Unknown")
    print(f"Impedance Switch: {impedance_str} ({impedance})")
    
    assert impedance in [1, 2, 3], f"Invalid impedance value: {impedance}"
    print("✓ PASS: Impedance switch read successfully\n")
    return True


def test_zone1_mode_switch(controller):
    """Test reading Zone 1 mode switch."""
    print("Test: Read Zone 1 Mode Switch")
    print("-" * 60)
    
    zone1_mode = controller.get_zone1_mode_switch()
    mode_map = {1: "Stereo", 2: "Bridged", 3: "Sum"}
    mode_str = mode_map.get(zone1_mode, "Unknown")
    print(f"Zone 1 Mode Switch (Ch 1-2): {mode_str} ({zone1_mode})")
    
    assert zone1_mode in [1, 2, 3], f"Invalid zone1 mode value: {zone1_mode}"
    print("✓ PASS: Zone 1 mode switch read successfully\n")
    return True


def test_zone2_mode_switch(controller):
    """Test reading Zone 2 mode switch."""
    print("Test: Read Zone 2 Mode Switch")
    print("-" * 60)
    
    zone2_mode = controller.get_zone2_mode_switch()
    mode_map = {1: "Stereo", 2: "Bridged", 3: "Sum"}
    mode_str = mode_map.get(zone2_mode, "Unknown")
    print(f"Zone 2 Mode Switch (Ch 3-4): {mode_str} ({zone2_mode})")
    
    assert zone2_mode in [1, 2, 3], f"Invalid zone2 mode value: {zone2_mode}"
    print("✓ PASS: Zone 2 mode switch read successfully\n")
    return True


def test_all_switches(controller):
    """Test reading all back panel switches at once."""
    print("Test: Read All Back Panel Switches")
    print("-" * 60)
    
    switches = controller.get_all_back_panel_switches()
    
    # Decode values
    power_str = "Always On" if switches['power_mode'] == 1 else "Power Saver"
    impedance_map = {1: "LoZ", 2: "100V", 3: "70V"}
    impedance_str = impedance_map.get(switches['impedance'], "Unknown")
    mode_map = {1: "Stereo", 2: "Bridged", 3: "Sum"}
    zone1_str = mode_map.get(switches['zone1_mode'], "Unknown")
    zone2_str = mode_map.get(switches['zone2_mode'], "Unknown")
    
    print("All Back Panel Switches:")
    print(f"  Power Mode:      {power_str} ({switches['power_mode']})")
    print(f"  Impedance:       {impedance_str} ({switches['impedance']})")
    print(f"  Zone 1 (Ch 1-2): {zone1_str} ({switches['zone1_mode']})")
    print(f"  Zone 2 (Ch 3-4): {zone2_str} ({switches['zone2_mode']})")
    
    assert 'power_mode' in switches
    assert 'impedance' in switches
    assert 'zone1_mode' in switches
    assert 'zone2_mode' in switches
    
    assert switches['power_mode'] in [0, 1], f"Invalid power_mode: {switches['power_mode']}"
    assert switches['impedance'] in [1, 2, 3], f"Invalid impedance: {switches['impedance']}"
    assert switches['zone1_mode'] in [1, 2, 3], f"Invalid zone1_mode: {switches['zone1_mode']}"
    assert switches['zone2_mode'] in [1, 2, 3], f"Invalid zone2_mode: {switches['zone2_mode']}"
    
    print("✓ PASS: All back panel switches read successfully\n")
    return True


def main():
    """Run all back panel switch tests."""
    # Get connection info from environment or use defaults
    config = {
        'ip': os.environ.get('X300_IP', '192.168.1.246'),
        'username': os.environ.get('X300_USERNAME', 'admin'),
        'password': os.environ.get('X300_PASSWORD', 'admin123'),
        'ssh_port': 6022,
        'model': 'X300'
    }
    
    print("=" * 60)
    print("X300 Back Panel Switch Tests")
    print("=" * 60)
    print(f"Device: {config['ip']}")
    print(f"Model:  {config['model']}")
    print()
    
    tests = [
        ("Power Mode Switch", test_power_mode_switch),
        ("Impedance Switch", test_impedance_switch),
        ("Zone 1 Mode Switch", test_zone1_mode_switch),
        ("Zone 2 Mode Switch", test_zone2_mode_switch),
        ("All Switches", test_all_switches)
    ]
    
    passed = 0
    failed = 0
    
    try:
        with X300Controller(config) as controller:
            for name, test_func in tests:
                try:
                    if test_func(controller):
                        passed += 1
                except Exception as e:
                    print(f"✗ FAIL: {name}")
                    print(f"  Error: {e}\n")
                    failed += 1
    except Exception as e:
        print(f"Error connecting to device: {e}", file=sys.stderr)
        return 1
    
    # Summary
    print("=" * 60)
    print("Test Summary")
    print("=" * 60)
    print(f"Total tests:  {passed + failed}")
    print(f"Passed:       {passed}")
    print(f"Failed:       {failed}")
    
    if failed == 0:
        print("\n✓ All tests passed!")
        return 0
    else:
        print(f"\n✗ {failed} test(s) failed")
        return 1


if __name__ == '__main__':
    sys.exit(main())
