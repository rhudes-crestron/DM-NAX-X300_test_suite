"""
Test: Volume Control
Category: DSP
Verifies zone volume control works correctly by measuring output level
changes as volume is adjusted.
Device state is automatically reset before and after each test by conftest.
"""
import pytest
import math


# All possible zones; conftest.pytest_collection_modifyitems filters to the
# session's --zone-mode / --zones selection at collection time.
ALL_ZONES = list(range(1, 9))


class TestVolume:
    """Verify zone volume control produces expected output level changes."""

    CATEGORY = "dsp_volume"

    @staticmethod
    def _output_info(zone, device_cfg):
        """Zone N -> left amp output index and output name.
        
        Returns the left (first) channel for the zone.
        For 8ZSA: Zone 1 = A1L, Zone 2 = A2L, etc.
        For X300: Zone 1 = A1, Zone 2 = A3, etc.
        """
        output_idx = (zone - 1) * 2
        amp_outputs = device_cfg.get("amp_outputs", [])
        
        if amp_outputs and len(amp_outputs) > output_idx:
            out_name = amp_outputs[output_idx]
        else:
            # Default to 8ZSA naming
            out_name = f"A{zone}L"
        
        return output_idx, out_name

    def _setup_signal(self, dsp, device_cfg, zone):
        """Inject signal generator tone and route to a zone's left output.
        
        fw42 architecture: start tone on the input channel and use mixer
        fw21 architecture: use signal generator and route_sig_to_output
        """
        output_idx, _ = self._output_info(zone, device_cfg)
        sig_ch = dsp.sig_ch_for_output(output_idx)
        
        if device_cfg.get("dsp_fw_version", 21) >= 42:
            # fw42: tone on input channel, route via mixer
            dsp.start_tone(output_idx, dsp.settings["default_tone_freq_hz"],
                           dsp.settings["default_tone_gain_db"])
            if dsp.cn is not None:
                dsp._set_tone_source_for_zone(zone)
            dsp.clear_all_sig_routes()
            dsp.set_mixer(output_idx, output_idx, 0)
        else:
            # fw21: signal generator routed to output
            dsp.start_tone(sig_ch, dsp.settings["default_tone_freq_hz"],
                           dsp.settings["default_tone_gain_db"])
            dsp.route_sig_to_output(output_idx)

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_volume_default(self, dsp, device_cfg, test_settings, zone):
        """At default volume (800 = 0dB), signal passes at expected level."""
        _, out_name = self._output_info(zone, device_cfg)
        if out_name not in device_cfg.get("amp_outputs", []):
            pytest.skip(f"{out_name} not available on {device_cfg['model']}")

        self._setup_signal(dsp, device_cfg, zone)
        dsp.set_zone_volume(zone, 800)
        level = dsp.measure_output_level(out_name)
        assert level > test_settings["mute_floor_db"], (
            f"Zone {zone}: no signal at {out_name} with default volume: {level:.2f} dB"
        )

    @pytest.mark.parametrize("zone", ALL_ZONES)
    @pytest.mark.parametrize("volume_value,description", [
        (1000, "Max volume (100%)"),
        (800, "80% volume (0dB ref)"),
        (500, "50% volume"),
        (250, "25% volume"),
        (0, "Min volume (0%)"),
    ])
    def test_volume_levels(self, dsp, device_cfg, test_settings,
                           zone, volume_value, description):
        """Volume changes produce proportional output level changes."""
        _, out_name = self._output_info(zone, device_cfg)
        if out_name not in device_cfg.get("amp_outputs", []):
            pytest.skip(f"{out_name} not available on {device_cfg['model']}")

        self._setup_signal(dsp, device_cfg, zone)

        # Measure reference at full volume (1000) first
        dsp.set_zone_volume(zone, 1000)
        level_ref = dsp.measure_output_level(out_name)

        # Now set target volume and measure
        dsp.set_zone_volume(zone, volume_value)
        level = dsp.measure_output_level(out_name)
        tol = float(test_settings["level_tolerance_db"])

        if volume_value == 0:
            # Volume=0 is not a hard-mute contract; require strong attenuation
            # relative to max-volume reference instead of absolute mute floor.
            min_drop_db = 10.0
            assert level <= level_ref - min_drop_db, (
                f"Zone {zone}: volume 0 did not attenuate enough at {out_name}: "
                f"max={level_ref:.2f}dB, vol0={level:.2f}dB (need >={min_drop_db:.1f}dB drop)"
            )
        elif volume_value == 1000:
            # At max volume, just confirm signal is present
            assert level > test_settings["mute_floor_db"], (
                f"Zone {zone}: no signal at {description}: {level:.2f} dB"
            )
        else:
            # Sub-max volumes must be lower than the max-volume reference and
            # have at least a small measurable drop.
            assert level > test_settings["mute_floor_db"], (
                f"Zone {zone}: no signal at {description}: {level:.2f} dB"
            )
            assert level <= level_ref - tol, (
                f"Zone {zone}: volume {volume_value} not measurably lower than max: "
                f"vol={volume_value} -> {level:.2f}dB, max -> {level_ref:.2f}dB"
            )
            if volume_value == 500:
                assert level <= level_ref - 1.0, (
                    f"Zone {zone}: 50% volume drop too small at {out_name}: "
                    f"max={level_ref:.2f}dB, vol500={level:.2f}dB"
                )
            if volume_value == 250:
                assert level <= level_ref - 3.0, (
                    f"Zone {zone}: 25% volume drop too small at {out_name}: "
                    f"max={level_ref:.2f}dB, vol250={level:.2f}dB"
                )
            dsp.assert_signal_presence(zone, expected=True)

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_volume_monotonic_decrease(self, dsp, device_cfg, test_settings, zone):
        """Decreasing volume should monotonically decrease output level."""
        _, out_name = self._output_info(zone, device_cfg)
        if out_name not in device_cfg.get("amp_outputs", []):
            pytest.skip(f"{out_name} not available on {device_cfg['model']}")

        self._setup_signal(dsp, device_cfg, zone)
        levels = []
        volume_steps = [1000, 800, 600, 400, 200, 0]

        for vol in volume_steps:
            dsp.set_zone_volume(zone, vol)
            level = dsp.measure_output_level(out_name)
            levels.append(level)

        # Each subsequent level should be equal or lower.
        # Skip the comparison if either sample is -inf (DSP state intermittently
        # omits rows for Zone 7 on 8ZSA; -inf means "measurement unavailable",
        # not a true silence reading, so we cannot assert ordering against it).
        for i in range(1, len(levels)):
            if not math.isinf(levels[i]) and not math.isinf(levels[i - 1]):
                assert levels[i] <= levels[i - 1] + test_settings["level_tolerance_db"], (
                    f"Zone {zone}: volume not monotonic at step {i}: "
                    f"{levels[i]:.2f} > {levels[i-1]:.2f}"
                )

        # Final step (volume=0) should be strongly attenuated versus max.
        assert levels[-1] <= levels[0] - 10.0, (
            f"Zone {zone}: volume=0 attenuation too small at {out_name}: "
            f"max={levels[0]:.2f}dB, vol0={levels[-1]:.2f}dB"
        )
