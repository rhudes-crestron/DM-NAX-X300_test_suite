"""
DM-NAX-X300 Basic Connectivity Tests

Verify basic SSH and HTTP connectivity to STM32MP1-based devices.
"""
import pytest
from lib.x300_controller import X300Controller


@pytest.mark.x300
@pytest.mark.quick
class TestBasicConnectivity:
    """Basic connectivity and device info tests."""
    
    def test_ssh_connection(self, device_config):
        """Test SSH connection to device."""
        device_name, config = device_config
        
        controller = X300Controller(config)
        controller.connect()
        
        # Verify connection by running simple command
        output = controller.run_command("echo 'test'")
        assert "test" in output.lower()
        
        controller.disconnect()
    
    def test_device_info(self, device_config):
        """Test retrieving device information."""
        device_name, config = device_config
        
        with X300Controller(config) as controller:
            info = controller.get_device_info()
            
            assert 'model' in info
            assert 'ip' in info
            assert 'platform' in info
            assert info['platform'] == 'STM32MP1'
    
    def test_uptime(self, device_config):
        """Test device uptime query."""
        device_name, config = device_config
        
        with X300Controller(config) as controller:
            output = controller.run_command("uptime")
            
            # Device should return uptime info
            assert output
            assert "load average" in output.lower() or "up" in output.lower()


@pytest.mark.x300
class TestAudioRouting:
    """Audio routing and control tests."""
    
    @pytest.mark.skip(reason="X300 routing not yet implemented")
    def test_route_input_to_output(self, device_config):
        """Test audio routing from input to output."""
        device_name, config = device_config
        
        with X300Controller(config) as controller:
            # TODO: Implement once X300 routing commands are known
            controller.route_audio("Input01", "Output01")
    
    @pytest.mark.quick
    def test_volume_control(self, device_config):
        """Test zone volume control."""
        device_name, config = device_config
        
        with X300Controller(config) as controller:
            # Start DSP processing
            controller.start_dsp()
            
            # Test setting volume on zone 1 (outputs 0-1)
            print("\nSetting zone 1 volume to 0 dB...")
            controller.set_volume(zone=1, level=0)
            
            # Verify by reading gain settings
            print("Reading zone 1 left channel (ch 0) gain...")
            output = controller.get_gain(0, 1)  # Channel 0, type 1 (output gain)
            assert output, "Should receive gain output"
            print(f"Output: {output[:200]}")
            
            # Test setting different levels
            print("\nSetting zone 1 volume to -6 dB...")
            controller.set_volume(zone=1, level=-6)
            
            print("\nSetting zone 1 volume to -12 dB...")
            controller.set_volume(zone=1, level=-12)
            
            # Reset to 0 dB
            print("\nResetting zone 1 volume to 0 dB...")
            controller.set_volume(zone=1, level=0)
            
            print("✓ Volume control test passed")


@pytest.mark.x300
class TestConfiguration:
    """Verify device configuration."""
    
    def test_config_has_required_fields(self, device_config):
        """Verify device configuration has all required fields."""
        device_name, config = device_config
        
        required_fields = ['ip', 'username', 'password', 'model', 'platform']
        
        for field in required_fields:
            assert field in config, f"Missing required field: {field}"
    
    def test_device_is_stm32mp1(self, device_config):
        """Verify device is STM32MP1-based."""
        device_name, config = device_config
        
        assert config['platform'] == 'STM32MP1'
        assert config['model'] in ['X300', 'XLR', 'BTIO', 'AUD_USB', 'AUD_IO', 'POE_SPK']


@pytest.mark.x300
class TestDSPModes:
    """Test DSP operating modes (residential vs commercial)."""
    
    @pytest.mark.quick
    def test_get_current_mode(self, device_config):
        """Test reading current DSP mode."""
        device_name, config = device_config
        
        with X300Controller(config) as controller:
            mode = controller.get_mode()
            print(f"\nCurrent mode: {mode}")
            
            assert mode in ['residential', 'commercial']
            print(f"✓ Device is in {mode} mode")
    
    def test_get_zone_count(self, device_config):
        """Test getting zone count based on mode."""
        device_name, config = device_config
        
        with X300Controller(config) as controller:
            mode = controller.get_mode()
            zone_count = controller.get_zone_count()
            
            print(f"\nMode: {mode}, Zone count: {zone_count}")
            
            if mode == 'residential':
                assert zone_count == 2, "Residential mode should have 2 zones"
            else:  # commercial
                assert zone_count == 4, "Commercial mode should have 4 channels"
            
            print(f"✓ Zone count correct for {mode} mode")
    
    @pytest.mark.parametrize("mode", ["residential", "commercial"])
    def test_set_mode(self, device_config, mode):
        """Test setting DSP mode."""
        device_name, config = device_config
        
        with X300Controller(config) as controller:
            # Get initial mode
            initial_mode = controller.get_mode()
            print(f"\nInitial mode: {initial_mode}")
            
            # Set new mode
            print(f"Setting mode to {mode}...")
            output = controller.set_mode(mode)
            print(f"Output: {output}")
            
            # Verify mode was set
            current_mode = controller.get_mode()
            assert current_mode == mode, f"Expected {mode}, got {current_mode}"
            print(f"✓ Mode set to {mode} successfully")
            
            # Restore initial mode
            if current_mode != initial_mode:
                print(f"Restoring initial mode: {initial_mode}...")
                controller.set_mode(initial_mode)


@pytest.mark.x300
class TestAmplifierControl:
    """Test amplifier zone control.
    
    HARDWARE LIMITATION: Amplifiers can only be controlled by zone pairs:
    - Zone 1: Controls channels 0-1
    - Zone 2: Controls channels 2-3
    """
    
    @pytest.mark.quick
    def test_get_amp_zone_status(self, device_config):
        """Test reading amplifier zone status."""
        device_name, config = device_config
        
        with X300Controller(config) as controller:
            zone1_status = controller.get_amp_zone_status(1)
            zone2_status = controller.get_amp_zone_status(2)
            
            print(f"\nAmplifier Zone Status:")
            print(f"  Zone 1 (ch 0-1): {'ENABLED' if zone1_status else 'DISABLED'}")
            print(f"  Zone 2 (ch 2-3): {'ENABLED' if zone2_status else 'DISABLED'}")
            
            assert isinstance(zone1_status, bool)
            assert isinstance(zone2_status, bool)
            print("✓ Amp zone status read successfully")
    
    def test_enable_disable_amp_zone(self, device_config):
        """Test enabling and disabling amplifier zones."""
        device_name, config = device_config
        
        with X300Controller(config) as controller:
            # Get initial state
            initial_zone1 = controller.get_amp_zone_status(1)
            initial_zone2 = controller.get_amp_zone_status(2)
            print(f"\nInitial state - Zone 1: {initial_zone1}, Zone 2: {initial_zone2}")
            
            # Test Zone 1
            print("\nTesting Zone 1 control...")
            controller.enable_amp_zone(1)
            assert controller.get_amp_zone_status(1) == True, "Zone 1 should be enabled"
            print("✓ Zone 1 enabled")
            
            controller.disable_amp_zone(1)
            assert controller.get_amp_zone_status(1) == False, "Zone 1 should be disabled"
            print("✓ Zone 1 disabled")
            
            # Test Zone 2
            print("\nTesting Zone 2 control...")
            controller.enable_amp_zone(2)
            assert controller.get_amp_zone_status(2) == True, "Zone 2 should be enabled"
            print("✓ Zone 2 enabled")
            
            controller.disable_amp_zone(2)
            assert controller.get_amp_zone_status(2) == False, "Zone 2 should be disabled"
            print("✓ Zone 2 disabled")
            
            # Restore initial state
            print("\nRestoring initial state...")
            if initial_zone1:
                controller.enable_amp_zone(1)
            if initial_zone2:
                controller.enable_amp_zone(2)
            print("✓ Initial state restored")
    
    @pytest.mark.quick
    def test_amp_always_on(self, device_config):
        """Test amplifier always-on mode."""
        device_name, config = device_config
        
        with X300Controller(config) as controller:
            # Get initial state
            initial_state = controller.get_amp_always_on()
            print(f"\nInitial always-on state: {initial_state}")
            
            # Test enabling
            controller.set_amp_always_on(True)
            assert controller.get_amp_always_on() == True, "Always-on should be enabled"
            print("✓ Always-on enabled")
            
            # Test disabling
            controller.set_amp_always_on(False)
            assert controller.get_amp_always_on() == False, "Always-on should be disabled"
            print("✓ Always-on disabled")
            
            # Restore initial state
            controller.set_amp_always_on(initial_state)
            print(f"✓ Restored initial state: {initial_state}")
    
    @pytest.mark.quick
    def test_signal_sense(self, device_config):
        """Test signal sense mode."""
        device_name, config = device_config
        
        with X300Controller(config) as controller:
            # Get initial state
            initial_state = controller.get_signal_sense()
            print(f"\nInitial signal sense state: {initial_state}")
            
            # Test enabling
            controller.set_signal_sense(True)
            assert controller.get_signal_sense() == True, "Signal sense should be enabled"
            print("✓ Signal sense enabled")
            
            # Test disabling
            controller.set_signal_sense(False)
            assert controller.get_signal_sense() == False, "Signal sense should be disabled"
            print("✓ Signal sense disabled")
            
            # Restore initial state
            controller.set_signal_sense(initial_state)
            print(f"✓ Restored initial state: {initial_state}")


@pytest.mark.x300
class TestBackPanelSwitches:
    """Test back panel hardware switch reading.
    
    These are physical DIP switches on the X300 back panel - read-only.
    Available on all X300 models.
    
    Back Panel Switches:
    1. Power Mode (2-position): Pwr Saver (0) / Always On (1)
    2. Impedance (3-position): LoZ (1) / 100V (2) / 70V (3)
    3. Zone 1 Mode (3-position): Stereo (1) / Bridged (2) / Sum (3)
    4. Zone 2 Mode (3-position): Stereo (1) / Bridged (2) / Sum (3)
    """
    
    @pytest.mark.quick
    def test_read_power_mode_switch(self, device_config):
        """Test reading power mode switch position."""
        device_name, config = device_config
        
        with X300Controller(config) as controller:
            power_mode = controller.get_power_mode_switch()
            
            mode_str = "Always On" if power_mode == 1 else "Power Saver"
            print(f"\nPower Mode Switch: {mode_str} ({power_mode})")
            
            assert power_mode in [0, 1], f"Invalid power mode value: {power_mode}"
            print("✓ Power mode switch read successfully")
    
    @pytest.mark.quick
    def test_read_impedance_switch(self, device_config):
        """Test reading impedance switch position."""
        device_name, config = device_config
        
        with X300Controller(config) as controller:
            impedance = controller.get_impedance_switch()
            
            impedance_map = {1: "LoZ", 2: "100V", 3: "70V"}
            impedance_str = impedance_map.get(impedance, "Unknown")
            print(f"\nImpedance Switch: {impedance_str} ({impedance})")
            
            assert impedance in [1, 2, 3], f"Invalid impedance value: {impedance}"
            print("✓ Impedance switch read successfully")
    
    @pytest.mark.quick
    def test_read_zone1_mode_switch(self, device_config):
        """Test reading Zone 1 (Ch 1-2) mode switch position."""
        device_name, config = device_config
        
        with X300Controller(config) as controller:
            zone1_mode = controller.get_zone1_mode_switch()
            
            mode_map = {1: "Stereo", 2: "Bridged", 3: "Sum"}
            mode_str = mode_map.get(zone1_mode, "Unknown")
            print(f"\nZone 1 Mode Switch (Ch 1-2): {mode_str} ({zone1_mode})")
            
            assert zone1_mode in [1, 2, 3], f"Invalid zone1 mode value: {zone1_mode}"
            print("✓ Zone 1 mode switch read successfully")
    
    @pytest.mark.quick
    def test_read_zone2_mode_switch(self, device_config):
        """Test reading Zone 2 (Ch 3-4) mode switch position."""
        device_name, config = device_config
        
        with X300Controller(config) as controller:
            zone2_mode = controller.get_zone2_mode_switch()
            
            mode_map = {1: "Stereo", 2: "Bridged", 3: "Sum"}
            mode_str = mode_map.get(zone2_mode, "Unknown")
            print(f"\nZone 2 Mode Switch (Ch 3-4): {mode_str} ({zone2_mode})")
            
            assert zone2_mode in [1, 2, 3], f"Invalid zone2 mode value: {zone2_mode}"
            print("✓ Zone 2 mode switch read successfully")
    
    @pytest.mark.quick
    def test_read_all_switches(self, device_config):
        """Test reading all back panel switches at once."""
        device_name, config = device_config
        
        with X300Controller(config) as controller:
            switches = controller.get_all_back_panel_switches()
            
            # Decode values
            power_str = "Always On" if switches['power_mode'] == 1 else "Power Saver"
            impedance_map = {1: "LoZ", 2: "100V", 3: "70V"}
            impedance_str = impedance_map.get(switches['impedance'], "Unknown")
            mode_map = {1: "Stereo", 2: "Bridged", 3: "Sum"}
            zone1_str = mode_map.get(switches['zone1_mode'], "Unknown")
            zone2_str = mode_map.get(switches['zone2_mode'], "Unknown")
            
            print(f"\nAll Back Panel Switches:")
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
            
            print("✓ All back panel switches read successfully")




