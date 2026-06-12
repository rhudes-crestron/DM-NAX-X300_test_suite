#!/usr/bin/env python3
"""
Standalone Mixer Routing Test for DM-NAX-X300

Tests mixer crosspoint routing on all channels based on current DSP mode
(Residential: 2 zones, Commercial: 4 channels)

Usage:
    python3 test_x300_mixer.py
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
    print("DM-NAX X300 Mixer Routing Test")
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
        
        print(f"  Mode: {mode_display}")
        print(f"  {zone_label}s: {zones}")
        
        print_header(f"Testing Mixer Routing - {mode_display} Mode")
        
        # Define test routing configurations
        # Each test routes input channel to output channel with gain
        test_routes = [
            {'input': 0, 'output': 0, 'gain_db': 0, 'description': 'CH0→OUT0 @ 0dB'},
            {'input': 0, 'output': 0, 'gain_db': -6, 'description': 'CH0→OUT0 @ -6dB'},
            {'input': 1, 'output': 1, 'gain_db': 0, 'description': 'CH1→OUT1 @ 0dB'},
            {'input': 0, 'output': 1, 'gain_db': 0, 'description': 'CH0→OUT1 @ 0dB (crosspoint)'},
        ]
        
        # Test each routing configuration
        for i, route in enumerate(test_routes):
            input_ch = route['input']
            output_ch = route['output']
            gain_db = route['gain_db']
            description = route['description']
            
            print(f"\n{'-' * 60}")
            print(f"Test {i+1}: {description}")
            print(f"{'-' * 60}")
            
            try:
                # Set mixer routing
                print(f"  Setting mixer: Input {input_ch} → Output {output_ch} @ {gain_db:+.1f} dB")
                result = controller.set_mixer(input_ch, output_ch, gain_db)
                print(f"  ✓ Mixer configured")
                
                # Small delay for settings to apply
                time.sleep(0.3)
                
                # Read back mixer configuration
                print(f"  Reading mixer state...")
                mixer_state = controller.get_mixer_config(input_ch, output_ch)
                if mixer_state:
                    # Display first line of response
                    first_line = mixer_state.split('\n')[0] if mixer_state else 'No output'
                    print(f"    Response: {first_line}")
                    print(f"  ✓ Mixer state verified")
                else:
                    print(f"  ⚠ No mixer state returned")
                    
            except Exception as e:
                print(f"  ✗ Error on routing {description}: {e}")
        
        # Read complete mixer state
        print_header("Complete Mixer State")
        try:
            print("Reading all mixer configurations...")
            mixer_output = controller.get_mixer_config()
            if mixer_output:
                lines = mixer_output.split('\n')
                print(f"\nMixer has {len(lines)} configuration lines:")
                # Display first 15 lines
                for line in lines[:15]:
                    if line.strip():
                        print(f"  {line}")
                if len(lines) > 15:
                    print(f"  ... ({len(lines) - 15} more lines)")
            else:
                print("  No mixer configuration returned")
        except Exception as e:
            print(f"  ✗ Error reading mixer state: {e}")
        
        print("\n" + "=" * 70)
        print("✓ Mixer routing test completed")
        print("=" * 70)
        
    finally:
        controller.disconnect()
        
except KeyboardInterrupt:
    print("\n\n⚠ Test interrupted by user")
    sys.exit(1)
except Exception as e:
    print(f"\n✗ Test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
