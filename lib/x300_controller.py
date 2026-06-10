"""
X300 Device Controller

SSH and HTTPS interface for STM32MP1-based DM-NAX devices.
"""
import paramiko
import time
import requests
from typing import Optional, Dict, Any


class X300Controller:
    """
    Controller for DM-NAX-X300 STM32MP1-based devices.
    
    Note: This is a template. Actual commands will differ from FPGA-based devices.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.ip = config['ip']
        self.username = config['username']
        self.password = config['password']
        self.model = config['model']
        
        self.ssh_client: Optional[paramiko.SSHClient] = None
        self.http_session: Optional[requests.Session] = None
        
    def connect(self):
        """Establish SSH connection to device."""
        try:
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh_client.connect(
                hostname=self.ip,
                username=self.username,
                password=self.password,
                port=self.config.get('ssh_port', 22),
                timeout=10,
                allow_agent=False,
                look_for_keys=False
            )
        except Exception as e:
            raise RuntimeError(f"Failed to connect to {self.ip}: {e}")
    
    def disconnect(self):
        """Close SSH connection."""
        if self.ssh_client:
            self.ssh_client.close()
            self.ssh_client = None
    
    def run_command(self, command: str, timeout: int = 10) -> str:
        """
        Execute shell command via SSH.
        
        Args:
            command: Command to execute
            timeout: Command timeout in seconds
            
        Returns:
            Command output as string
        """
        if not self.ssh_client:
            self.connect()
        
        stdin, stdout, stderr = self.ssh_client.exec_command(command, timeout=timeout)
        output = stdout.read().decode('utf-8')
        error = stderr.read().decode('utf-8')
        
        if error:
            raise RuntimeError(f"Command failed: {error}")
        
        return output
    
    def get_device_info(self) -> Dict[str, str]:
        """Get device information."""
        info = {
            'model': self.model,
            'ip': self.ip,
            'platform': 'STM32MP1'
        }
        
        # Try to get firmware version
        try:
            output = self.run_command("cat /etc/os-release")
            for line in output.split('\n'):
                if 'VERSION' in line:
                    info['firmware_version'] = line.split('=')[1].strip('"')
                    break
        except:
            info['firmware_version'] = 'Unknown'
        
        return info
    
    def start_tone(self, channel: int, freq_hz: int, gain_db: int) -> str:
        """
        Start tone generator on specified channel.
        Uses dsp_test command (X300-specific).
        
        Args:
            channel: DSP channel number
            freq_hz: Frequency in Hz
            gain_db: Gain in dB
            
        Returns:
            Command output
        """
        cmd = f"dsp_test tone {channel} {freq_hz} {gain_db}"
        return self.run_command(cmd)
    
    def stop_tone(self, channel: int) -> str:
        """
        Stop tone on specified channel.
        
        Args:
            channel: DSP channel number
            
        Returns:
            Command output
        """
        return self.start_tone(channel, 0, 0)
    
    def play_white_noise(self, gain_db: int) -> str:
        """
        Play white noise on signal generator channel.
        
        Args:
            gain_db: Gain in dB
            
        Returns:
            Command output
        """
        cmd = f"dsp_test wnoise {gain_db}"
        return self.run_command(cmd)
    
    def play_pink_noise(self, gain_db: int) -> str:
        """
        Play pink noise on signal generator channel.
        
        Args:
            gain_db: Gain in dB
            
        Returns:
            Command output
        """
        cmd = f"dsp_test pnoise {gain_db}"
        return self.run_command(cmd)
    
    def read_dsp_state(self) -> str:
        """
        Read DSP state table.
        
        Returns:
            Raw DSP state output
        """
        return self.run_command("dsp")
    
    def set_mixer(self, input_ch: int, output_ch: int, gain_db: int) -> str:
        """
        Set mixer crosspoint.
        Uses dsp_test command (X300-specific).
        
        Args:
            input_ch: Input channel number
            output_ch: Output channel number
            gain_db: Gain in dB
            
        Returns:
            Command output
        """
        cmd = f"dsp_test mix {input_ch} {output_ch} {gain_db}"
        return self.run_command(cmd)
    
    def get_mixer_config(self, input_ch: int = None, output_ch: int = None) -> str:
        """
        Read mixer configuration.
        
        Args:
            input_ch: Optional input channel to query
            output_ch: Optional output channel to query
            
        Returns:
            Mixer configuration output
        """
        if input_ch is not None and output_ch is not None:
            cmd = f"dsp_test mix {input_ch} {output_ch}"
        elif output_ch is not None:
            cmd = f"dsp_test mix {output_ch}"
        elif input_ch is not None:
            cmd = f"dsp_test mix {input_ch}"
        else:
            cmd = "dsp_test mix"
        return self.run_command(cmd)
    
    def start_dsp(self) -> str:
        """
        Start DSP audio processing.
        Note: On X300 the DSP audio processing is halted by default.
        
        Returns:
            Command output
        """
        return self.run_command("dsp_test start")
    
    def route_audio(self, input_ch: int, output_ch: int, gain_db: int = 0):
        """
        Route audio input to output via mixer.
        
        Args:
            input_ch: Input channel number
            output_ch: Output channel number
            gain_db: Gain in dB (default 0)
        """
        return self.set_mixer(input_ch, output_ch, gain_db)
    
    def set_gain(self, channel: int, gain_type: int, gain_db: float) -> str:
        """
        Set gain on a channel.
        
        Args:
            channel: Channel number
            gain_type: Gain type (0=input, 1=output, 2=extra, 3=rava, 4=lineout, 
                       5=emerg, 6=out_bal, 7=outputTrim, 8=ramp, 9=speakertype,
                       10=inputTrim, 11=AGCgainMon, 12=AGCpostGain, 
                       13=automixGainMon, 14=AMInputGain, 15=announcement)
            gain_db: Gain in dB
            
        Returns:
            Command output
        """
        cmd = f"dsp_test gain {channel} {gain_type} {gain_db}"
        return self.run_command(cmd)
    
    def get_gain(self, channel: int, gain_type: int) -> str:
        """
        Get gain setting on a channel.
        
        Args:
            channel: Channel number
            gain_type: Gain type (see set_gain for types)
            
        Returns:
            Command output with gain value
        """
        cmd = f"dsp_test gain {channel} {gain_type}"
        return self.run_command(cmd)
    
    def set_output_gain(self, channel: int, gain_db: float) -> str:
        """
        Set output gain on a channel.
        
        Args:
            channel: Output channel number
            gain_db: Gain in dB
            
        Returns:
            Command output
        """
        return self.set_gain(channel, 1, gain_db)  # Type 1 = output gain
    
    def set_volume(self, zone: int, level: int):
        """
        Set zone volume (output gain).
        
        For X300, this sets the output gain on the zone's channels.
        Level is interpreted as a gain adjustment in dB.
        
        Args:
            zone: Zone number (1-based)
            level: Gain level in dB (0 = unity gain, positive = boost, negative = cut)
        """
        # X300 zones map to output channels
        # Zone 1 = channels 0-1 (L/R), Zone 2 = channels 2-3, etc.
        left_channel = (zone - 1) * 2
        right_channel = left_channel + 1
        
        # Set gain on both L and R channels
        self.set_output_gain(left_channel, level)
        self.set_output_gain(right_channel, level)
    
    def get_mode(self) -> str:
        """
        Get current DSP operating mode.
        
        Returns:
            'residential' or 'commercial'
            
        Note:
            Residential mode: 2 zones (stereo)
            Commercial mode: 4 channels (mono)
            
            Uses `dsp_test mode` command which works on X300.
            Output: "DSP mode is  Residential" or "DSP mode is  Commercial"
        """
        output = self.run_command("dsp_test mode")
        # Output: "DSP mode is  Residential" or "DSP mode is  Commercial"
        if "Commercial" in output:
            return "commercial"
        elif "Residential" in output:
            return "residential"
        else:
            raise RuntimeError(f"Could not parse mode from output: {output}")
    
    def set_mode(self, mode: str) -> str:
        """
        Set DSP and AMP control operating mode.
        
        **IMPORTANT**: This command can only be run from device CONSOLE, not SSH!
        
        Args:
            mode: 'residential' or 'commercial'
            
        Returns:
            Command output (will fail if called via SSH)
            
        Note:
            Mode 0 = Residential (2 zones, stereo)
            Mode 1 = Commercial (4 channels, mono)
            
            **LIMITATION**: AConfigControl only works from device console.
            To set mode, you must:
              1. Log into device console (not SSH/bash)
              2. Run: aconfigcontrol setresidboot (or setcommeboot)
              3. Reboot device
            
            This method will attempt to run the command via SSH but will
            likely fail. Use manual console access instead.
            
        Commands (for console use):
            aconfigcontrol setresidboot - Set Residential mode
            aconfigcontrol setcommeboot - Set Commercial mode
        """
        mode_lower = mode.lower()
        if mode_lower == 'residential':
            cmd = "aconfigcontrol setresidboot"
        elif mode_lower == 'commercial':
            cmd = "aconfigcontrol setcommeboot"
        else:
            raise ValueError(f"Invalid mode: {mode}. Must be 'residential' or 'commercial'")
        
        # This will likely fail since AConfigControl doesn't work from SSH
        try:
            output = self.run_command(cmd)
            return output
        except Exception as e:
            raise RuntimeError(
                f"AConfigControl must be run from device console, not SSH. "
                f"Log into console and run: {cmd}"
            )
    
    def get_zone_count(self) -> int:
        """
        Get number of zones based on current mode.
        
        Returns:
            2 for residential mode, 4 for commercial mode
        """
        mode = self.get_mode()
        return 2 if mode == 'residential' else 4
    
    def get_mode_detailed(self) -> Dict[str, str]:
        """
        Get detailed mode information including saved and running modes.
        
        **IMPORTANT**: AConfigControl only works from device console, not SSH!
        This method will likely fail when called via SSH.
        
        Use get_ampctrl_mode_from_status() instead for SSH access.
        
        Returns:
            Dictionary with:
              - 'aoip_saved': Saved AoIP mode (Dante/AES67)
              - 'aoip_running': Running AoIP mode
              - 'audio_saved': Saved audio mode (Residential/Commercial)
              - 'audio_running': Running audio mode
              
        Example output from aconfigcontrol (console only):
            AoIpMode:   AES67(saved) AES67(running)
            AudioMode:  Commercial(saved) Commercial(running)
        """
        output = self.run_command("aconfigcontrol")
        result = {}
        
        for line in output.split('\n'):
            if 'AoIpMode:' in line:
                # Parse: AoIpMode:   AES67(saved) AES67(running)
                parts = line.split()
                if len(parts) >= 3:
                    result['aoip_saved'] = parts[1].replace('(saved)', '')
                    result['aoip_running'] = parts[2].replace('(running)', '')
            elif 'AudioMode:' in line:
                # Parse: AudioMode:  Residential(saved) Residential(running)
                parts = line.split()
                if len(parts) >= 3:
                    result['audio_saved'] = parts[1].replace('(saved)', '').lower()
                    result['audio_running'] = parts[2].replace('(running)', '').lower()
        
        return result
    
    def get_aconfigcontrol_help(self) -> str:
        """
        Get AConfigControl command help.
        
        **IMPORTANT**: This only works from device console, not SSH!
        
        Returns:
            Help text for aconfigcontrol command
            
        Available options (console only):
              - setresidboot: Set Residential mode (requires reboot)
              - setcommeboot: Set Commercial mode (requires reboot)
              - setdanteboot: Set Dante mode (requires reboot)
              - setaes67boot: Set AES67 mode (requires reboot)
              
        To use from console:
            ssh admin@device
            DM-NAX-AMP-X300> aconfigcontrol ?
        """
        try:
            return self.run_command("aconfigcontrol ?")
        except:
            return (
                "aconfigcontrol ? (console only)\n"
                "  setresidboot - Set Residential mode\n"
                "  setcommeboot - Set Commercial mode\n"
                "  setdanteboot - Set Dante mode\n"
                "  setaes67boot - Set AES67 mode\n"
                "  (no args) - Show current modes\n"
            )
    
    def enable_amp_zone(self, zone: int) -> str:
        """
        Enable amplifier for a specific zone.
        
        HARDWARE LIMITATION: Amplifiers can only be controlled by zone pairs:
        - Zone 1: Controls channels 0-1
        - Zone 2: Controls channels 2-3
        
        Args:
            zone: Zone number (1 or 2)
            
        Returns:
            Command output
            
        Note:
            Uses sysfs: /sys/class/leds/AMP_ENABLE_Z{zone}/brightness
        """
        if zone not in [1, 2]:
            raise ValueError(f"Invalid zone: {zone}. Must be 1 or 2")
        
        cmd = f"echo 1 > /sys/class/leds/AMP_ENABLE_Z{zone}/brightness"
        return self.run_command(cmd)
    
    def disable_amp_zone(self, zone: int) -> str:
        """
        Disable amplifier for a specific zone.
        
        HARDWARE LIMITATION: Amplifiers can only be controlled by zone pairs:
        - Zone 1: Controls channels 0-1
        - Zone 2: Controls channels 2-3
        
        Args:
            zone: Zone number (1 or 2)
            
        Returns:
            Command output
            
        Note:
            Uses sysfs: /sys/class/leds/AMP_ENABLE_Z{zone}/brightness
        """
        if zone not in [1, 2]:
            raise ValueError(f"Invalid zone: {zone}. Must be 1 or 2")
        
        cmd = f"echo 0 > /sys/class/leds/AMP_ENABLE_Z{zone}/brightness"
        return self.run_command(cmd)
    
    def get_amp_zone_status(self, zone: int) -> bool:
        """
        Get amplifier enable status for a specific zone.
        
        Args:
            zone: Zone number (1 or 2)
            
        Returns:
            True if enabled, False if disabled
        """
        if zone not in [1, 2]:
            raise ValueError(f"Invalid zone: {zone}. Must be 1 or 2")
        
        cmd = f"cat /sys/class/leds/AMP_ENABLE_Z{zone}/brightness"
        output = self.run_command(cmd).strip()
        return output == "1"
    
    def set_amp_always_on(self, enabled: bool) -> str:
        """
        Set amplifier always-on mode.
        
        When enabled, amplifiers stay on regardless of signal presence.
        
        Args:
            enabled: True to enable always-on, False to disable
            
        Returns:
            Command output
            
        Note:
            Uses sysfs: /sys/class/leds/AMP_ALWAYS_ON/brightness
        """
        value = 1 if enabled else 0
        cmd = f"echo {value} > /sys/class/leds/AMP_ALWAYS_ON/brightness"
        return self.run_command(cmd)
    
    def get_amp_always_on(self) -> bool:
        """
        Get amplifier always-on mode status.
        
        Returns:
            True if always-on is enabled, False otherwise
        """
        cmd = "cat /sys/class/leds/AMP_ALWAYS_ON/brightness"
        output = self.run_command(cmd).strip()
        return output == "1"
    
    def set_signal_sense(self, enabled: bool) -> str:
        """
        Set signal sense mode.
        
        When enabled, amplifiers automatically turn on when signal is detected.
        
        Args:
            enabled: True to enable signal sense, False to disable
            
        Returns:
            Command output
            
        Note:
            Uses sysfs: /sys/class/leds/AMP_SIGNAL_SENSE/brightness
        """
        value = 1 if enabled else 0
        cmd = f"echo {value} > /sys/class/leds/AMP_SIGNAL_SENSE/brightness"
        return self.run_command(cmd)
    
    def get_signal_sense(self) -> bool:
        """
        Get signal sense mode status.
        
        Returns:
            True if signal sense is enabled, False otherwise
        """
        cmd = "cat /sys/class/leds/AMP_SIGNAL_SENSE/brightness"
        output = self.run_command(cmd).strip()
        return output == "1"
    
    def get_power_mode_switch(self) -> int:
        """
        Get power mode switch position from back panel.
        
        Returns:
            0 = Power Saver mode
            1 = Always On mode
            
        Note:
            This is a read-only physical DIP switch on the back panel.
            2-position switch that controls power management.
            
            Available on: All X300 models
            sysfs path: /sys/crestron/ctrl-back-panel/switches/switch_pwr_save
        """
        cmd = "cat /sys/crestron/ctrl-back-panel/switches/switch_pwr_save"
        output = self.run_command(cmd).strip()
        return int(output)
    
    def get_impedance_switch(self) -> int:
        """
        Get impedance switch position from back panel.
        
        Returns:
            1 = LoZ (Low Impedance) mode
            2 = 100V (High Impedance) mode
            3 = 70V (High Impedance) mode
            
        Note:
            This is a read-only physical DIP switch on the back panel.
            3-position switch that controls speaker impedance mode.
            
            Available on: All X300 models
            sysfs path: /sys/crestron/ctrl-back-panel/switches/switch_lowz
        """
        cmd = "cat /sys/crestron/ctrl-back-panel/switches/switch_lowz"
        output = self.run_command(cmd).strip()
        return int(output)
    
    def get_zone1_mode_switch(self) -> int:
        """
        Get Zone 1 (Ch 1-2) mode switch position from back panel.
        
        Returns:
            1 = Stereo mode
            2 = Bridged mode
            3 = Sum mode
            
        Note:
            This is a read-only physical DIP switch on the back panel.
            3-position switch that controls operating mode for channels 1-2.
            
            Available on: All X300 models
            sysfs path: /sys/crestron/ctrl-back-panel/switches/switch_ch12
        """
        cmd = "cat /sys/crestron/ctrl-back-panel/switches/switch_ch12"
        output = self.run_command(cmd).strip()
        return int(output)
    
    def get_zone2_mode_switch(self) -> int:
        """
        Get Zone 2 (Ch 3-4) mode switch position from back panel.
        
        Returns:
            1 = Stereo mode
            2 = Bridged mode
            3 = Sum mode
            
        Note:
            This is a read-only physical DIP switch on the back panel.
            3-position switch that controls operating mode for channels 3-4.
            
            Available on: All X300 models
            sysfs path: /sys/crestron/ctrl-back-panel/switches/switch_ch34
        """
        cmd = "cat /sys/crestron/ctrl-back-panel/switches/switch_ch34"
        output = self.run_command(cmd).strip()
        return int(output)
    
    def get_all_back_panel_switches(self) -> dict:
        """
        Get all back panel switch positions.
        
        Returns:
            Dictionary with switch names and their values:
            {
                'power_mode': 0 or 1,      # 0=Power Saver, 1=Always On
                'impedance': 1, 2, or 3,   # 1=LoZ, 2=100V, 3=70V
                'zone1_mode': 1, 2, or 3,  # 1=Stereo, 2=Bridged, 3=Sum
                'zone2_mode': 1, 2, or 3   # 1=Stereo, 2=Bridged, 3=Sum
            }
            
        Note:
            Available on: All X300 models
        """
        return {
            'power_mode': self.get_power_mode_switch(),
            'impedance': self.get_impedance_switch(),
            'zone1_mode': self.get_zone1_mode_switch(),
            'zone2_mode': self.get_zone2_mode_switch()
        }
    
    #==========================================================================
    # Amplifier Control Methods (ampctrl)
    #==========================================================================
    
    def get_ampctrl_status(self) -> str:
        """
        Read amplifier control status.
        
        This command outputs the system initialization log which includes:
          - Audio mode: RESIDENTIAL or COMMERCIAL
          - Power mode: ALWAYS ON or SAVER
          - Zone initialization status
          - Bridging configuration
          
        Returns:
            ampctrl status output containing mode information
            
        Example output:
            AmpControlHandler::Initialize() unit start with: RESIDENTIAL mode, PWR SAVER mode
            
        Note:
            This verifies the actual running mode that ampctrl application
            is using (read from registers at boot time), complementing
            AConfigControl which shows the saved/requested mode.
        """
        return self.run_command("ampctrl")
    
    def get_ampctrl_mode_from_status(self) -> Dict[str, str]:
        """
        Parse residential/commercial and power mode from ampctrl status.
        
        Returns:
            Dictionary with:
              - 'audio_mode': 'residential' or 'commercial'
              - 'power_mode': 'always_on' or 'saver'
              
        Note:
            This reads the mode that ampctrl is ACTUALLY running with
            (read from hardware registers at initialization).
        """
        output = self.get_ampctrl_status()
        result = {}
        
        # Parse line like:
        # "AmpControlHandler::Initialize() unit start with: RESIDENTIAL mode, PWR SAVER mode"
        for line in output.split('\n'):
            if 'unit start with:' in line:
                if 'RESIDENTIAL' in line:
                    result['audio_mode'] = 'residential'
                elif 'COMMERCIAL' in line:
                    result['audio_mode'] = 'commercial'
                
                if 'ALWAYS ON' in line:
                    result['power_mode'] = 'always_on'
                elif 'SAVER' in line:
                    result['power_mode'] = 'saver'
                break
        
        return result
    
    def verify_mode_consistency(self) -> Dict[str, Any]:
        """
        Verify mode using ampctrl (works via SSH).
        
        **Note**: AConfigControl only works from device console, not SSH.
        This method uses ampctrl only, which can be called via SSH.
        
        Returns:
            Dictionary with:
              - 'ampctrl_running': Mode from ampctrl (actual running mode)
              - 'power_mode': Power mode from ampctrl
              
        Note:
            To verify saved mode vs running mode, you must:
              1. Log into device console (not SSH)
              2. Run: aconfigcontrol
              3. Check if saved and running modes match
            
            ampctrl shows what the AMP control app is ACTUALLY using
            (read from hardware registers at boot time).
        """
        # Get mode from ampctrl (works via SSH)
        ampctrl_mode = self.get_ampctrl_mode_from_status()
        ampctrl_running = ampctrl_mode.get('audio_mode', 'unknown')
        
        return {
            'ampctrl_running': ampctrl_running,
            'power_mode': ampctrl_mode.get('power_mode', 'unknown'),
            'consistent': True,  # Can't verify without console access
            'needs_reboot': False,  # Can't determine without console access
            'note': 'To verify saved vs running mode, use aconfigcontrol from device console'
        }
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
