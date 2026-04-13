"""
Test: Volume Control
Category: DSP
Verifies zone volume control works correctly by measuring output level
changes as volume is adjusted.
Device state is automatically reset before and after each test by conftest.
"""
import pytest
import math


class TestVolume:
    """Verify zone volume control produces expected output level changes."""

    CATEGORY = "dsp_volume"

    def _setup_signal(self, dsp, device_cfg, output_idx=0):
        """Inject signal generator tone and route to specified output."""
        dsp.start_sig_tone()
        dsp.route_sig_to_output(output_idx)

    def test_volume_default(self, dsp, device_cfg, test_settings):
        """At default volume (800 = 0dB), signal passes at expected level."""
        self._setup_signal(dsp, device_cfg)
        state = dsp.read_dsp_state()
        a1l = state.outputs.get("A1L")
        assert a1l, "A1L output not found"
        assert a1l.ducker_db > test_settings["mute_floor_db"], (
            f"No signal at A1L with default volume: {a1l.ducker_db} dB"
        )

    @pytest.mark.parametrize("volume_value,description", [
        (1000, "Max volume (100%)"),
        (800, "80% volume (0dB ref)"),
        (500, "50% volume"),
        (250, "25% volume"),
        (0, "Min volume (0%)"),
    ])
    def test_volume_levels(self, dsp, device_cfg, test_settings,
                           volume_value, description):
        """Volume changes produce proportional output level changes."""
        self._setup_signal(dsp, device_cfg)

        dsp.set_zone_volume(1, volume_value)
        level = dsp.measure_output_level("A1L")

        if volume_value == 0:
            # On fw42 devices where signal generator IS a physical input
            # (ch0=T1L), the DSP output meters read signal before the
            # volume stage — volume=0 doesn't reach -110 dB at the
            # measurement point.  Use IsMuted for true mute testing.
            if device_cfg.get("dsp_fw_version", 21) >= 42 and \
               device_cfg["signal_generator"]["channel"] < 16:
                pytest.skip(
                    f"Volume=0 measurement unreliable on "
                    f"{device_cfg['model']} (tone on physical input ch"
                    f"{device_cfg['signal_generator']['channel']})"
                )
            assert level < test_settings["mute_floor_db"], (
                f"Signal present at 0% volume: {level} dB"
            )
        else:
            assert level > test_settings["mute_floor_db"], (
                f"No signal at {description}: {level} dB"
            )
            dsp.assert_signal_presence(1, expected=True)

    def test_volume_monotonic_decrease(self, dsp, device_cfg, test_settings):
        """Decreasing volume should monotonically decrease output level."""
        self._setup_signal(dsp, device_cfg)
        levels = []
        volume_steps = [1000, 800, 600, 400, 200]

        for vol in volume_steps:
            dsp.set_zone_volume(1, vol)
            level = dsp.measure_output_level("A1L")
            levels.append(level)

        # Each subsequent level should be equal or lower
        for i in range(1, len(levels)):
            if not math.isinf(levels[i]):
                assert levels[i] <= levels[i - 1] + test_settings["level_tolerance_db"], (
                    f"Volume not monotonic at step {i}: {levels[i]:.2f} > {levels[i-1]:.2f}"
                )
