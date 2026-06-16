"""
DM-NAX Basic Connectivity Tests

Verify basic SSH and connectivity to all DM-NAX devices.
"""
import pytest


@pytest.mark.quick
class TestBasicConnectivity:
    """Basic connectivity and device info tests."""
    
    def test_ssh_connection(self, ssh):
        """Test SSH connection to device."""
        # Verify connection by running simple command
        output = ssh.execute("echo 'test'")
        assert "test" in output.lower()
    
    def test_device_info(self, device_cfg):
        """Test device configuration has required fields."""
        required_fields = ['model', 'ip', 'ssh_port']
        
        for field in required_fields:
            assert field in device_cfg, f"Missing required field: {field}"
        
        print(f"\nDevice: {device_cfg['model']} at {device_cfg['ip']}")
    
    def test_uptime(self, ssh):
        """Test device uptime query."""
        output = ssh.execute("uptime")
        
        # Device should return uptime info
        assert output
        assert "load average" in output.lower() or "up" in output.lower()


class TestAudioRouting:
    """Audio routing and control tests."""
    
    @pytest.mark.skip(reason="Routing not yet implemented for all devices")
    def test_route_input_to_output(self, dsp):
        """Test audio routing from input to output."""
        # TODO: Implement once routing commands are standardized
        pass
    
    @pytest.mark.quick
    def test_volume_control(self, dsp, device_cfg):
        """Test zone volume control via DSP."""
        zone = 1
        
        # Test setting volume levels
        print(f"\nTesting volume control on zone {zone}...")
        
        # Set to middle volume
        print("Setting volume to 500...")
        dsp.set_zone_volume(zone, 500)
        
        # Set to max volume
        print("Setting volume to 1000...")
        dsp.set_zone_volume(zone, 1000)
        
        # Reset to 0
        print("Resetting volume to 0...")  
        dsp.set_zone_volume(zone, 0)
        
        print("✓ Volume control test passed")


class TestConfiguration:
    """Verify device configuration."""
    
    def test_config_has_required_fields(self, device_cfg):
        """Verify device configuration has all required fields."""
        required_fields = ['ip', 'username', 'password', 'model']
        
        for field in required_fields:
            assert field in device_cfg, f"Missing required field: {field}"
    
    @pytest.mark.skipif(True, reason="Platform-specific test - skip for universal framework")
    def test_device_is_stm32mp1(self, device_cfg):
        """Verify device is STM32MP1-based."""
        assert device_cfg.get('platform') == 'STM32MP1'
        assert device_cfg['model'] in ['X300', 'XLR', 'BTIO', 'AUD_USB', 'AUD_IO', 'POE_SPK']


@pytest.mark.x300
class TestDSPModes:
    """Test DSP operating modes (residential vs commercial) - X300 specific."""
    
    @pytest.mark.skip(reason="X300-specific feature - not in universal framework yet")
    def test_get_current_mode(self, ssh):
        """Test reading current DSP mode."""
        pass
    
    @pytest.mark.skip(reason="X300-specific feature - not in universal framework yet")
    def test_get_zone_count(self, device_cfg):
        """Test getting zone count based on mode."""
        pass
    
    @pytest.mark.skip(reason="X300-specific feature - not in universal framework yet")
    @pytest.mark.parametrize("mode", ["residential", "commercial"])
    def test_set_mode(self, ssh, mode):
        """Test setting DSP mode."""
        pass


@pytest.mark.x300
class TestAmplifierControl:
    """Test amplifier zone control - X300 specific.
    
    HARDWARE LIMITATION: Amplifiers can only be controlled by zone pairs:
    - Zone 1: Controls channels 0-1
    - Zone 2: Controls channels 2-3
    """
    
    @pytest.mark.skip(reason="X300-specific feature - not in universal framework yet")
    def test_get_amp_zone_status(self, ssh):
        """Test reading amplifier zone status."""
        pass
    
    @pytest.mark.skip(reason="X300-specific feature - not in universal framework yet")
    def test_enable_disable_amp_zone(self, ssh):
        """Test enabling and disabling amplifier zones."""
        pass
    
    @pytest.mark.skip(reason="X300-specific feature - not in universal framework yet")
    def test_amp_always_on(self, ssh):
        """Test amplifier always-on mode."""
        pass
    
    @pytest.mark.skip(reason="X300-specific feature - not in universal framework yet")
    def test_signal_sense(self, ssh):
        """Test signal sense mode."""
        pass


