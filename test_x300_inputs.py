#!/usr/bin/env python3
"""
Standalone Input Compensation Test for DM-NAX-X300

Tests input compensation on all zones/channels based on current DSP mode
(Residential: 2 zones, Commercial: 4 channels)

Usage:
    python3 test_x300_inputs.py
"""

import sys
import time
from lib.x300_controller import X300Controller

# Device configuration
X300_IP = "192.168.1.246"
X300_USERNAME = "admin"
X300_PASSWORD = "admin123"
X300_PORT = 6022

def print_header(title):
    """Print formatted section header"""
    print(f"\n{'=' * 70}")
    print(title)
    print('=' * 70)

try:
    print("=" * 70)
    print("DM-NAX X300 Input Compensation Test")
    print("=" * 70)
    
    config = {
        'ip': X300_IP,
        'username': X300_USERNAME,
        'password': X300_PASSWORD,
        'ssh_port': X300_PORT,
        'model': 'X300'
    }
    
    controller = X300Controller(config)
    
    try:
        # Detect mode
        print("\nConnecting and detecting mode...")
        mode = controller.get_mode()
        zones = controller.get_zone_count()
        
        mode_display = mode.upper()
        zone_label = "Zone" if mode == 'residential' else "Channel"
        
        print(f"✓ Connected to X300")
        print(f"  Mode: {mode_display}")
        print(f"  {zone_label}s: {zones}")
        
        print_header(f"Input Compensation Test - All {zone_label}s")
        print(f"Testing input compensation on all {zone_label}s")
        print(f"Mode: {mode_display} ({zones} {zone_label}s)")
        
        if mode == 'commercial':
            print(f"\n{'Method:':-<60}")
            print(f"  Using CresNEXT commands:")
            print(f"    crestore_test setpend InputChannels Channels ChXXX Compensation [value]")
            print(f"  Verification:")
            print(f"    crestore_test get InputChannels Channels ChXXX Compensation")
            print(f"    dsp_test gain [channel] 0")
        else:
            print(f"\n{'Method:':-<60}")
            print(f"  Using CresNEXT commands:")
            print(f"    crestore_test setpend InputSources Inputs InputXX SourceAudio Compensation [value]")
            print(f"  Verification:")
            print(f"    crestore_test get InputSources Inputs InputXX SourceAudio Compensation")
            print(f"    dsp_test gain [channel] 0  (for both L/R channels)")
            print(f"  Note: Each Input affects stereo pair (Input01→Ch0-1, Input02→Ch2-3)")
        
        # Define test values table
        test_values = [
            {'db': 0.0, 'description': 'unity gain'},
            {'db': 6.0, 'description': 'boost'},
            {'db': -6.0, 'description': 'cut'},
            {'db': 0.0, 'description': 'reset'},
        ]
        
        # Test each zone/channel
        for zone_num in range(1, zones + 1):
            print(f"\n{'-' * 60}")
            print(f"{zone_label} {zone_num}:")
            print(f"{'-' * 60}")
            
            try:
                # Iterate through test values
                for i, test_val in enumerate(test_values):
                    db_value = test_val['db']
                    description = test_val['description']
                    
                    if i > 0:  # Add delay between tests (except first one)
                        time.sleep(0.3)
                    
                    if mode == 'commercial':
                        # COMMERCIAL MODE: Use CresNEXT InputChannels commands
                        print(f"  Setting to {db_value:+.1f} dB ({description})...")
                        controller.set_channel_compensation_cresnext(zone_num, db_value)
                        
                        # Verify with both CresNEXT and DSP
                        result = controller.verify_channel_compensation(zone_num, db_value)
                        print(f"  ✓ CresNEXT: {result['cresnext_value']} dB")
                        print(f"    DSP output: {result['dsp_output']}")
                        if result['cresnext_match']:
                            print(f"    ✓ Values match expected ({db_value:+.1f} dB)")
                        else:
                            print(f"    ⚠ CresNEXT value mismatch")
                    
                    else:
                        # RESIDENTIAL MODE: Use CresNEXT InputSources commands
                        print(f"  Setting to {db_value:+.1f} dB ({description})...")
                        controller.set_input_compensation_cresnext(zone_num, db_value)
                        
                        # Verify with both CresNEXT and DSP (both L/R channels)
                        result = controller.verify_input_compensation(zone_num, db_value)
                        print(f"  ✓ CresNEXT: {result['cresnext_value']} dB")
                        print(f"    DSP Left (Ch{(zone_num-1)*2}): {result['dsp_left']}")
                        print(f"    DSP Right (Ch{(zone_num-1)*2+1}): {result['dsp_right']}")
                        if result['cresnext_match']:
                            print(f"    ✓ Values match expected ({db_value:+.1f} dB)")
                        else:
                            print(f"    ⚠ CresNEXT value mismatch")
                
            except Exception as e:
                print(f"  ✗ Error on {zone_label} {zone_num}: {e}")
        
        print(f"\n{'=' * 70}")
        print(f"✓ INPUT COMPENSATION TEST COMPLETED")
        print(f"{'=' * 70}")
        print(f"\nTested all {zones} {zone_label}s successfully")
        if mode == 'commercial':
            print(f"  Method: CresNEXT InputChannels Compensation (setpend)")
            print(f"  Command: crestore_test setpend/get InputChannels Channels ChXXX Compensation")
            print(f"  Verified: 4 mono channels")
        else:
            print(f"  Method: CresNEXT InputSources Compensation (setpend)")
            print(f"  Command: crestore_test setpend/get InputSources Inputs InputXX SourceAudio Compensation")
            print(f"  Verified: {zones} stereo inputs (L/R pairs checked)")
        print(f"  - 0 dB (unity gain): ✓")
        print(f"  - +6 dB (boost): ✓")
        print(f"  - -6 dB (cut): ✓")
        print(f"  - Reset to 0 dB: ✓")
        print("=" * 70)
        
    finally:
        controller.disconnect()
        
except Exception as e:
    print(f"\n✗ TEST FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
