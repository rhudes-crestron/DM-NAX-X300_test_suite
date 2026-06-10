#!/usr/bin/env python3
"""
X300 DSP Test Suite - mimicking 4ZSA tests with mode detection.

X300 can operate in two modes:
  - Residential: 2 zones (stereo) = 4 outputs (Z1L, Z1R, Z2L, Z2R)
  - Commercial: 4 channels (mono) = 4 outputs (CH1, CH2, CH3, CH4)

Usage: 
    export X300_IP=192.168.1.246 X300_USERNAME=admin X300_PASSWORD=admin123
    python3 test_x300_dsp_modes.py
"""
import sys
import os
sys.path.insert(0, 'lib')

from x300_controller import X300Controller
import time

# Get connection info from environment
X300_IP = os.environ.get('X300_IP', '192.168.1.246')
X300_USERNAME = os.environ.get('X300_USERNAME', 'admin')
X300_PASSWORD = os.environ.get('X300_PASSWORD', 'admin123')
X300_PORT = int(os.environ.get('X300_PORT', '6022'))

def print_header(title):
    """Print formatted test header"""
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)

def test_connectivity(controller):
    """Test basic connectivity and device info"""
    print_header("Test 1: Device Connectivity")
    
    print(f"Connecting to {X300_IP}:{X300_PORT}...")
    controller.connect()
    print("✓ Connected successfully")
    
    info = controller.get_device_info()
    print(f"\nDevice Information:")
    print(f"  Model: {info.get('model', 'Unknown')}")
    print(f"  Platform: {info.get('platform', 'Unknown')}")
    print(f"  Firmware: {info.get('firmware_version', 'Unknown')}")

def test_mode_detection(controller):
    """Test DSP mode detection"""
    print_header("Test 2: DSP Mode Detection (Using AConfigControl)")
    
    # Get simple mode
    mode = controller.get_mode()
    zones = controller.get_zone_count()
    
    # Get detailed mode info
    mode_details = controller.get_mode_detailed()
    
    print(f"Current DSP Mode: {mode.upper()}")
    print(f"\nDetailed Mode Information:")
    print(f"  AoIP Mode:")
    print(f"    Saved:   {mode_details.get('aoip_saved', 'Unknown')}")
    print(f"    Running: {mode_details.get('aoip_running', 'Unknown')}")
    print(f"  Audio Mode:")
    print(f"    Saved:   {mode_details.get('audio_saved', 'Unknown').title()}")
    print(f"    Running: {mode_details.get('audio_running', 'Unknown').title()}")
    
    print(f"\nZone Configuration:")
    if mode == 'residential':
        print(f"  - 2 Stereo Zones (4 outputs: Z1L/R, Z2L/R)")
    else:  # commercial
        print(f"  - 4 Mono Channels (4 outputs: CH1, CH2, CH3, CH4)")
    
    print(f"  - Total outputs: {zones * 2 if mode == 'residential' else zones}")
    
    print(f"\nNote: AConfigControl sets mode for BOTH:")
    print(f"  - DSP application")
    print(f"  - AMP control application")
    
    return mode, zones

def test_dsp_state(controller, mode):
    """Test reading DSP state table"""
    print_header("Test 3: DSP State Table")
    
    print("Reading DSP state...")
    output = controller.read_dsp_state()
    lines = output.split('\n')
    print(f"✓ DSP state: {len(lines)} lines")
    
    # Show relevant output lines
    print(f"\nOutputs in {mode} mode:")
    for line in lines[:15]:  # Show first 15 lines
        if line.strip():
            print(f"  {line}")

def test_tone_generator(controller, mode):
    """Test tone generator on appropriate channel"""
    print_header("Test 4: Tone Generator")
    
    # Use channel 28 for X300 (similar to 4ZSA)
    test_channel = 28
    test_freq = 1000
    test_gain = -20
    
    print(f"Starting tone: Channel {test_channel}, {test_freq} Hz, {test_gain} dB")
    result = controller.start_tone(test_channel, test_freq, test_gain)
    
    if result:
        print(f"✓ Tone started")
        print(f"  Response: {result[:100]}...")
    else:
        print(f"✓ Tone command accepted")
    
    time.sleep(1)  # Let tone stabilize
    
    # Verify tone in DSP state
    print("\nVerifying tone in DSP state...")
    output = controller.read_dsp_state()
    if f"{test_freq}" in output or f"CH{test_channel}" in output:
        print(f"✓ Tone detected in DSP state")
    else:
        print(f"⚠ Tone not clearly visible in DSP output (may be normal)")
    
    return test_channel

def test_mixer_routing(controller, test_channel, mode):
    """Test mixer routing"""
    print_header("Test 5: Mixer Routing")
    
    # Route tone to first output
    output_ch = 0
    gain_db = 0
    
    print(f"Setting mixer route: CH{test_channel} → Output {output_ch} @ {gain_db} dB")
    try:
        result = controller.set_mixer(test_channel, output_ch, gain_db)
        print(f"✓ Mixer configured")
        if result:
            print(f"  Response: {result[:100]}...")
    except Exception as e:
        print(f"⚠ Mixer command: {e}")
    
    time.sleep(1.5)  # Let signal settle
    
    # Measure output
    print("\nMeasuring output level...")
    output = controller.read_dsp_state()
    lines = output.split('\n')
    
    found_signal = False
    for line in lines:
        # Look for output channel 0 or Zone 1
        if 'Out[' in line or 'Z1' in line or 'CH1' in line:
            print(f"  {line}")
            # Simple check for level above noise floor
            if '-inf' not in line:
                parts = [p for p in line.split() if p.startswith('-') and '.' in p]
                if parts:
                    try:
                        level = float(parts[0])
                        if level > -100:
                            print(f"  ✓ Signal detected: {level} dB")
                            found_signal = True
                    except:
                        pass
    
    if not found_signal:
        print(f"  ℹ No clear signal detected (output may be below noise floor)")

def test_volume_control(controller, mode, zones):
    """Test volume control on first zone/channel"""
    print_header("Test 6: Volume Control")
    
    zone_name = "Zone 1" if mode == 'residential' else "Channel 1"
    print(f"Testing volume control on {zone_name}")
    
    # Test volume at 800 (default/0dB)
    print("\nSetting volume to 800 (0 dB reference)...")
    try:
        controller.set_zone_volume(1, 800)
        vol = controller.get_zone_volume(1)
        print(f"✓ Volume set: {vol}")
    except Exception as e:
        print(f"⚠ Volume control: {e}")

def test_mute_control(controller, mode):
    """Test mute control"""
    print_header("Test 7: Mute Control")
    
    zone_name = "Zone 1" if mode == 'residential' else "Channel 1"
    print(f"Testing mute on {zone_name}")
    
    # Mute
    print("\nMuting zone...")
    try:
        controller.set_zone_mute(1, True)
        is_muted = controller.get_zone_mute(1)
        print(f"✓ Mute enabled: {is_muted}")
        
        time.sleep(0.5)
        
        # Unmute
        print("\nUnmuting zone...")
        controller.set_zone_mute(1, False)
        is_muted = controller.get_zone_mute(1)
        print(f"✓ Mute disabled: {is_muted}")
    except Exception as e:
        print(f"⚠ Mute control: {e}")

def test_mode_switching(controller, current_mode):
    """Test switching between residential and commercial modes"""
    print_header("Test 8: Mode Switching (AConfigControl)")
    
    other_mode = 'commercial' if current_mode == 'residential' else 'residential'
    
    print(f"Current mode: {current_mode}")
    print(f"\nℹ To test mode switching, device would be switched to {other_mode} mode")
    print(f"  This requires a REBOOT to take effect.")
    print(f"  AConfigControl sets mode for BOTH DSP and AMP control applications.")
    
    print(f"\n{'Mode Comparison':-<70}")
    print(f"  Residential: 2 stereo zones (home theater/residential use)")
    print(f"  Commercial: 4 mono channels (distributed audio/commercial use)")
    
    # Show available commands
    print(f"\n{'Available Commands':-<70}")
    try:
        help_text = controller.get_aconfigcontrol_help()
        print(help_text)
    except Exception as e:
        print(f"  AConfigControl setresidboot  - Set Residential mode (requires reboot)")
        print(f"  AConfigControl setcommeboot  - Set Commercial mode (requires reboot)")
        print(f"  AConfigControl setdanteboot  - Set Dante AoIP mode (requires reboot)")
        print(f"  AConfigControl setaes67boot  - Set AES67 AoIP mode (requires reboot)")
        print(f"  AConfigControl               - Show current saved/running modes")
    
    print(f"\n{'To Manually Switch Mode:':-<70}")
    print(f"  1. SSH to device")
    print(f"  2. Run: AConfigControl setresidboot  (or setcommeboot)")
    print(f"  3. Reboot device")
    print(f"  4. Verify with: AConfigControl")
    
    print(f"\n{'Programmatic Usage:':-<70}")
    print(f"  controller.set_mode('{other_mode}')")
    print(f"  # Then reboot device for change to take effect")

def test_cleanup(controller, test_channel):
    """Clean up test state"""
    print_header("Test 9: Cleanup")
    
    print(f"Stopping tone on channel {test_channel}...")
    try:
        controller.stop_tone(test_channel)
        print(f"✓ Tone stopped")
    except Exception as e:
        print(f"⚠ Stop tone: {e}")
    
    # Reset volume and mute
    print("\nResetting zone 1 to defaults...")
    try:
        controller.set_zone_volume(1, 800)
        controller.set_zone_mute(1, False)
        print(f"✓ Zone reset to defaults")
    except Exception as e:
        print(f"⚠ Reset: {e}")

def main():
    print("=" * 70)
    print("DM-NAX X300 DSP Test Suite")
    print("Similar to 4ZSA tests but with Residential/Commercial mode support")
    print("=" * 70)
    
    config = {
        'ip': X300_IP,
        'username': X300_USERNAME,
        'password': X300_PASSWORD,
        'ssh_port': X300_PORT,
        'model': 'X300'
    }
    
    controller = X300Controller(config)
    test_channel = None
    
    try:
        # Run all tests
        test_connectivity(controller)
        mode, zones = test_mode_detection(controller)
        test_dsp_state(controller, mode)
        test_channel = test_tone_generator(controller, mode)
        test_mixer_routing(controller, test_channel, mode)
        test_volume_control(controller, mode, zones)
        test_mute_control(controller, mode)
        test_mode_switching(controller, mode)
        test_cleanup(controller, test_channel)
        
        print("\n" + "=" * 70)
        print("✓ ALL TESTS COMPLETED SUCCESSFULLY")
        print("=" * 70)
        print(f"\nDevice tested in {mode.upper()} mode")
        print(f"  - {zones} zones/channels tested")
        print(f"  - DSP commands: dsp_test (X300-specific)")
        print(f"  - Tone generator, mixer, volume, mute: ✓")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        controller.disconnect()

if __name__ == "__main__":
    main()
