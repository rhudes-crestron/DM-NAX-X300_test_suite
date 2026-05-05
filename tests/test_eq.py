"""
Test: Parametric EQ (PEQ) — per speaker zone
Category: DSP

Follows EQ-Speaker{N} sheets (Zones 1–8) and EQ-LineOutBypass sheet in
AP_TestCases.xlsx.  Each zone receives an identical EQ test sequence; a DSP
tone generator + output_db readback is used as a proxy for the Audio
Precision frequency-sweep measurement performed in the hardware test lab.

Per-zone setup (from spreadsheet setup rows):
  • Route DSP tone bus (Input05) to Zone N via AvMatrixRouting / StreamRoutings
  • Set Zone Volume = 800  (0 dB reference, matching spreadsheet "Set Zone to
    Volume 0dB" rows)
    • All PEQ bands flat: Gain=0, Type=EQ, Freq=32, BW=33

    CresNext scaling note (from DspAudioCtl/CresStore mapping):
    • Bandwidth is stored as integer with scale 0.01 oct (valid 10..400)
        e.g. UI 1.00 oct → CresNext 100, default 0.33 oct → 33.

Filter-type audio path tests (Band01: Gain=+100 (+10 dB), Freq=2000 Hz,
BW=100 (1.00 oct) — matching "PEq 1 Test" and subsequent filter-type rows):

  Filter type    Test tone   Expected delta
  -----------    ---------   --------------
  EQ (peak)      2000 Hz     ≥ +6 dB  (PEq 1 Test)
  EQ (cut)       2000 Hz     ≤ -6 dB  (negative Gain)
  BassShelf      200 Hz      ≥ +4 dB  (Low Shelf Test)
  TrebleShelf    8000 Hz     ≥ +4 dB  (High Shelf Test)
  HighPass       200 Hz      ≤ -6 dB  (Low Cut Test)
  LowPass        8000 Hz     ≤ -6 dB  (High Cut Test)

Bypass tests (from "Eq Zone Bypass Test" and "Eq Band Bypass Test" rows):
  • Zone bypass ON  → output returns near flat  (≤ BYPASS_TOLERANCE_DB)
  • Zone bypass OFF → output returns to boosted level
  • Band bypass ON  → output returns near flat
  • Band bypass OFF → output returns to boosted level

CresNext paths:
  Band:    /Device/ZoneOutputs/Zones/Zone{N}/ZoneAudio/Peq/Bands/Band{NN}/
  Bypass:  /Device/ZoneOutputs/Zones/Zone{N}/ZoneAudio/ → IsEqBypassEnabled
  LineOut: /Device/ZoneOutputs/Zones/Zone{N}/ZoneAudio/ → IsLineOutEqBypassEnabled
"""
import pytest
import time

# Default band state from "Set to Default" rows in AP_TestCases.xlsx
BAND_DEFAULT = {
    "Type": "EQ",
    "Gain": 0,
    "Frequency": 32,
    "Bandwidth": 33,
    "IsEqBypassEnabled": False,
}

# PEQ-1 parameters shared by all filter-type tests (from EQ-Speaker sheets)
# Band01: Gain=+100 (+10.0 dB), BW=100 (1.00 oct), Freq=2000 Hz, Type varies
PEQ1_BASE = {
    "Gain": 100,
    "Bandwidth": 100,
    "Frequency": 2000,
    "IsEqBypassEnabled": False,
}

# Audio path thresholds
MIN_BOOST_DB        = 6.0   # EQ peak / shelf boost must exceed this
MIN_SHELF_BOOST_DB  = 4.0   # shelf at test freq may be slightly less than peak
MIN_ATTN_DB         = 6.0   # HP / LP attenuation magnitude must exceed this
BYPASS_TOLERANCE_DB = 2.5   # when bypassed, output must be within this of flat

# Zones parametrized — conftest.pytest_collection_modifyitems deselects
# any zone outside the session's --zone-mode / --zones selection.
ALL_ZONES = list(range(1, 9))


class TestEQ:
    """
    Parametric EQ audio-path tests following AP_TestCases.xlsx EQ-Speaker sheets.

    Every test that changes an EQ parameter ALSO measures the DSP output_db
    at a frequency chosen to expose the filter's effect, verifying that the
    CresNext property change actually propagates through the DSP audio path.
    """

    CATEGORY = "dsp_eq"
    _BAND = 1   # Band01 is used throughout, matching the spreadsheet

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _output_info(zone):
        """Map zone number to (output_channel_index, output_name).

        Zone N → left amp output A{N}L → DSP output channel (N-1)*2.
        """
        return (zone - 1) * 2, f"A{zone}L"

    def _setup_zone(self, dsp, cn, device_cfg, test_settings,
                    zone, freq_hz, tone_gain_db=-30):
        """
        Route DSP tone to Zone N's left amp output and set Volume=800 (0 dB).

        Matches the per-zone setup in each EQ-Speaker sheet:
          - route_sig_to_output handles AvMatrixRouting / StreamRoutings
          - Volume=800 matches "Set Zone to Volume 0dB" spreadsheet rows

        Returns (sig_ch, output_name).
        Calls pytest.skip() if the zone is beyond the device's zone count.
        """
        max_zones = device_cfg.get("zones", 4)
        if zone > max_zones:
            pytest.skip(
                f"Zone {zone} not available on {device_cfg['model']} (max {max_zones})"
            )

        output_idx, output_name = self._output_info(zone)
        if output_name not in device_cfg.get("amp_outputs", []):
            pytest.skip(f"{output_name} not in amp_outputs for {device_cfg['model']}")

        sig_ch = dsp.sig_ch  # Always use primary sig channel for zone-chain tests
        dsp.start_tone(sig_ch, freq_hz, tone_gain_db)
        dsp.route_sig_to_output(output_idx)
        cn.set_zone_audio(zone, Volume=800)
        time.sleep(test_settings["signal_settle_time_s"])
        return sig_ch, output_name

    def _flat_band(self, cn, zone):
        """Reset Band01 to default flat state for the given zone."""
        cn.set_peq_band(zone, self._BAND, **BAND_DEFAULT)
        cn.set_zone_audio(zone, IsEqBypassEnabled=False)

    def _apply_peq(self, cn, zone, eq_type="EQ", **overrides):
        """Apply PEQ-1 to Band01 for the given zone (flat zone bypass)."""
        params = {**PEQ1_BASE, "Type": eq_type, **overrides}
        cn.set_peq_band(zone, self._BAND, **params)
        cn.set_zone_audio(zone, IsEqBypassEnabled=False)

    def _measure(self, dsp, output_name, test_settings):
        """Read settled output_db for the named DSP output."""
        return dsp.measure_output_level(
            output_name, settle_time=test_settings["signal_settle_time_s"]
        )

    # ==================================================================
    # Per-zone tests — parametrized over ALL_ZONES
    # (conftest deselects zones outside the active --zone-mode selection)
    # ==================================================================

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_flat_signal_present(self, dsp, cresnext, device_cfg, test_settings, zone):
        """
        Flat step: signal is audible at zone output with Volume=800 and all EQ flat.
        Matches the initial 'Flat' AP measurement row in each EQ-Speaker sheet.
        Verifies the signal path is established before any EQ is applied.
        """
        sig_ch = None
        try:
            sig_ch, output_name = self._setup_zone(
                dsp, cresnext, device_cfg, test_settings, zone, 1000
            )
            self._flat_band(cresnext, zone)
            level = self._measure(dsp, output_name, test_settings)
            assert level > test_settings["mute_floor_db"], (
                f"Zone {zone} ({output_name}): no signal at flat EQ, Volume=800 — "
                f"measured {level:.2f} dB"
            )
            dsp.assert_signal_presence(zone, expected=True)
        finally:
            if sig_ch is not None:
                self._flat_band(cresnext, zone)
                dsp.stop_tone(sig_ch)

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_peq_boost_at_bandfreq(self, dsp, cresnext, device_cfg, test_settings, zone):
        """
        PEq 1 Test: EQ peak +10 dB at 2 kHz raises measured output at 2 kHz by ≥ 6 dB.
        Band01: Type=EQ, Gain=100, Freq=2000, BW=100.

        Verifies both:
          1. CresNext reflects all four band properties (Type, Gain, Frequency, Bandwidth).
          2. DSP output_db at 2 kHz increases by at least MIN_BOOST_DB after applying the band.
        """
        sig_ch = None
        try:
            sig_ch, output_name = self._setup_zone(
                dsp, cresnext, device_cfg, test_settings, zone, 2000
            )
            self._flat_band(cresnext, zone)
            baseline = self._measure(dsp, output_name, test_settings)
            assert baseline > test_settings["mute_floor_db"], (
                f"Zone {zone}: no signal at flat baseline (2 kHz) — {baseline:.2f} dB"
            )

            self._apply_peq(cresnext, zone, eq_type="EQ")

            # CresNext readback
            band = cresnext.get_peq_band(zone, self._BAND)
            assert band.get("Type")      == "EQ",  f"Zone {zone} Band01 Type: {band.get('Type')}"
            assert band.get("Gain")      == 100,   f"Zone {zone} Band01 Gain: {band.get('Gain')}"
            assert band.get("Frequency") == 2000,  f"Zone {zone} Band01 Freq: {band.get('Frequency')}"
            assert band.get("Bandwidth") == 100,   f"Zone {zone} Band01 BW: {band.get('Bandwidth')}"

            # Audio path verification
            boosted = self._measure(dsp, output_name, test_settings)
            delta = boosted - baseline
            assert delta >= MIN_BOOST_DB, (
                f"Zone {zone} ({output_name}): PEQ +10 dB peak at 2 kHz — "
                f"expected delta ≥ {MIN_BOOST_DB} dB, "
                f"baseline={baseline:.2f}, boosted={boosted:.2f}, delta={delta:.2f} dB"
            )
        finally:
            if sig_ch is not None:
                self._flat_band(cresnext, zone)
                dsp.stop_tone(sig_ch)

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_peq_cut_at_bandfreq(self, dsp, cresnext, device_cfg, test_settings, zone):
        """
        EQ cut -10 dB at 2 kHz reduces measured output at 2 kHz by ≥ 6 dB.
        Band01: Type=EQ, Gain=-100, Freq=2000, BW=100.

        Verifies both:
          1. CresNext reflects negative Gain correctly.
          2. DSP output_db at 2 kHz decreases by at least MIN_BOOST_DB.
        """
        sig_ch = None
        try:
            sig_ch, output_name = self._setup_zone(
                dsp, cresnext, device_cfg, test_settings, zone, 2000, tone_gain_db=-20
            )
            self._flat_band(cresnext, zone)
            baseline = self._measure(dsp, output_name, test_settings)
            assert baseline > test_settings["mute_floor_db"], (
                f"Zone {zone}: no signal at flat baseline (2 kHz) — {baseline:.2f} dB"
            )

            self._apply_peq(cresnext, zone, eq_type="EQ", Gain=-100)

            band = cresnext.get_peq_band(zone, self._BAND)
            assert band.get("Gain") == -100, (
                f"Zone {zone} Band01 Gain=-100 readback: {band.get('Gain')}"
            )

            cut = self._measure(dsp, output_name, test_settings)
            delta = cut - baseline
            assert delta <= -MIN_BOOST_DB, (
                f"Zone {zone} ({output_name}): PEQ -10 dB cut at 2 kHz — "
                f"expected delta ≤ -{MIN_BOOST_DB} dB, "
                f"baseline={baseline:.2f}, cut={cut:.2f}, delta={delta:.2f} dB"
            )
        finally:
            if sig_ch is not None:
                self._flat_band(cresnext, zone)
                dsp.stop_tone(sig_ch)

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_bassshelf_boosts_lowfreq(self, dsp, cresnext, device_cfg, test_settings, zone):
        """
        Low Shelf Test: BassShelf +10 dB (knee@2 kHz) boosts output at 200 Hz.
        Band01: Type=BassShelf, Gain=100, Freq=2000, BW=100.
        200 Hz sits well below the shelf knee — full boost region expected.

        Verifies both:
          1. CresNext reflects Type=BassShelf.
          2. DSP output_db at 200 Hz increases by at least MIN_SHELF_BOOST_DB.
        """
        sig_ch = None
        try:
            sig_ch, output_name = self._setup_zone(
                dsp, cresnext, device_cfg, test_settings, zone, 200
            )
            self._flat_band(cresnext, zone)
            baseline = self._measure(dsp, output_name, test_settings)
            assert baseline > test_settings["mute_floor_db"], (
                f"Zone {zone}: no signal at flat baseline (200 Hz) — {baseline:.2f} dB"
            )

            self._apply_peq(cresnext, zone, eq_type="BassShelf")

            band = cresnext.get_peq_band(zone, self._BAND)
            assert band.get("Type") == "BassShelf", (
                f"Zone {zone} Band01 Type readback: {band.get('Type')}"
            )

            boosted = self._measure(dsp, output_name, test_settings)
            delta = boosted - baseline
            assert delta >= MIN_SHELF_BOOST_DB, (
                f"Zone {zone} ({output_name}): BassShelf +10 dB@2 kHz, tone@200 Hz — "
                f"expected delta ≥ {MIN_SHELF_BOOST_DB} dB, "
                f"baseline={baseline:.2f}, boosted={boosted:.2f}, delta={delta:.2f} dB"
            )
        finally:
            if sig_ch is not None:
                self._flat_band(cresnext, zone)
                dsp.stop_tone(sig_ch)

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_trebleshelf_boosts_highfreq(self, dsp, cresnext, device_cfg, test_settings, zone):
        """
        High Shelf Test: TrebleShelf +10 dB (knee@2 kHz) boosts output at 8 kHz.
        Band01: Type=TrebleShelf, Gain=100, Freq=2000, BW=100.
        8 kHz sits two octaves above the shelf knee — full boost region expected.

        Verifies both:
          1. CresNext reflects Type=TrebleShelf.
          2. DSP output_db at 8 kHz increases by at least MIN_SHELF_BOOST_DB.
        """
        sig_ch = None
        try:
            sig_ch, output_name = self._setup_zone(
                dsp, cresnext, device_cfg, test_settings, zone, 8000
            )
            self._flat_band(cresnext, zone)
            baseline = self._measure(dsp, output_name, test_settings)
            assert baseline > test_settings["mute_floor_db"], (
                f"Zone {zone}: no signal at flat baseline (8 kHz) — {baseline:.2f} dB"
            )

            self._apply_peq(cresnext, zone, eq_type="TrebleShelf")

            band = cresnext.get_peq_band(zone, self._BAND)
            assert band.get("Type") == "TrebleShelf", (
                f"Zone {zone} Band01 Type readback: {band.get('Type')}"
            )

            boosted = self._measure(dsp, output_name, test_settings)
            delta = boosted - baseline
            assert delta >= MIN_SHELF_BOOST_DB, (
                f"Zone {zone} ({output_name}): TrebleShelf +10 dB@2 kHz, tone@8 kHz — "
                f"expected delta ≥ {MIN_SHELF_BOOST_DB} dB, "
                f"baseline={baseline:.2f}, boosted={boosted:.2f}, delta={delta:.2f} dB"
            )
        finally:
            if sig_ch is not None:
                self._flat_band(cresnext, zone)
                dsp.stop_tone(sig_ch)

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_highpass_attenuates_lowfreq(self, dsp, cresnext, device_cfg, test_settings, zone):
        """
        Low Cut Test: HighPass filter at 2 kHz attenuates tone at 200 Hz.
        Band01: Type=HighPass, Gain=100, Freq=2000, BW=100.
        200 Hz is 3.3 octaves below the cutoff — deep attenuation expected.

        Verifies both:
          1. CresNext reflects Type=HighPass.
          2. DSP output_db at 200 Hz drops by at least MIN_ATTN_DB below flat.
        """
        sig_ch = None
        try:
            sig_ch, output_name = self._setup_zone(
                dsp, cresnext, device_cfg, test_settings, zone, 200, tone_gain_db=-20
            )
            self._flat_band(cresnext, zone)
            baseline = self._measure(dsp, output_name, test_settings)
            assert baseline > test_settings["mute_floor_db"], (
                f"Zone {zone}: no signal at flat baseline (200 Hz) — {baseline:.2f} dB"
            )

            self._apply_peq(cresnext, zone, eq_type="HighPass")

            band = cresnext.get_peq_band(zone, self._BAND)
            assert band.get("Type") == "HighPass", (
                f"Zone {zone} Band01 Type readback: {band.get('Type')}"
            )

            attenuated = self._measure(dsp, output_name, test_settings)
            delta = attenuated - baseline
            assert delta <= -MIN_ATTN_DB, (
                f"Zone {zone} ({output_name}): HighPass cutoff@2 kHz, tone@200 Hz — "
                f"expected delta ≤ -{MIN_ATTN_DB} dB, "
                f"baseline={baseline:.2f}, attenuated={attenuated:.2f}, delta={delta:.2f} dB"
            )
        finally:
            if sig_ch is not None:
                self._flat_band(cresnext, zone)
                dsp.stop_tone(sig_ch)

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_lowpass_attenuates_highfreq(self, dsp, cresnext, device_cfg, test_settings, zone):
        """
        High Cut Test: LowPass filter at 2 kHz attenuates tone at 8 kHz.
        Band01: Type=LowPass, Gain=100, Freq=2000, BW=100.
        8 kHz is two octaves above the cutoff — clear attenuation expected.

        Verifies both:
          1. CresNext reflects Type=LowPass.
          2. DSP output_db at 8 kHz drops by at least MIN_ATTN_DB below flat.
        """
        sig_ch = None
        try:
            sig_ch, output_name = self._setup_zone(
                dsp, cresnext, device_cfg, test_settings, zone, 8000, tone_gain_db=-20
            )
            self._flat_band(cresnext, zone)
            baseline = self._measure(dsp, output_name, test_settings)
            assert baseline > test_settings["mute_floor_db"], (
                f"Zone {zone}: no signal at flat baseline (8 kHz) — {baseline:.2f} dB"
            )

            self._apply_peq(cresnext, zone, eq_type="LowPass")

            band = cresnext.get_peq_band(zone, self._BAND)
            assert band.get("Type") == "LowPass", (
                f"Zone {zone} Band01 Type readback: {band.get('Type')}"
            )

            attenuated = self._measure(dsp, output_name, test_settings)
            delta = attenuated - baseline
            assert delta <= -MIN_ATTN_DB, (
                f"Zone {zone} ({output_name}): LowPass cutoff@2 kHz, tone@8 kHz — "
                f"expected delta ≤ -{MIN_ATTN_DB} dB, "
                f"baseline={baseline:.2f}, attenuated={attenuated:.2f}, delta={delta:.2f} dB"
            )
        finally:
            if sig_ch is not None:
                self._flat_band(cresnext, zone)
                dsp.stop_tone(sig_ch)

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_zone_bypass_cancels_eq(self, dsp, cresnext, device_cfg, test_settings, zone):
        """
        Eq Zone Bypass Test from EQ-Speaker sheets:
          1. Apply PEQ-1 boost (Band01: EQ +10 dB@2 kHz).  Verify it is active.
          2. IsEqBypassEnabled=True  → output returns near flat (AP: Flat limits).
             CresNext readback must reflect True.
          3. IsEqBypassEnabled=False → EQ is restored (AP: PEq-1 limits).
             CresNext readback must reflect False.
        """
        sig_ch = None
        try:
            sig_ch, output_name = self._setup_zone(
                dsp, cresnext, device_cfg, test_settings, zone, 2000
            )
            self._flat_band(cresnext, zone)
            flat = self._measure(dsp, output_name, test_settings)
            assert flat > test_settings["mute_floor_db"], (
                f"Zone {zone}: no signal at flat baseline — {flat:.2f} dB"
            )

            # Activate EQ
            self._apply_peq(cresnext, zone, eq_type="EQ")
            active = self._measure(dsp, output_name, test_settings)
            assert active >= flat + MIN_BOOST_DB * 0.5, (
                f"Zone {zone}: EQ not active before bypass test — "
                f"flat={flat:.2f}, active={active:.2f} dB"
            )

            # Bypass ON → should return to flat
            cresnext.set_zone_audio(zone, IsEqBypassEnabled=True)
            bypassed = self._measure(dsp, output_name, test_settings)
            za = cresnext.get_zone_audio(zone)
            assert za.get("IsEqBypassEnabled") is True, (
                f"Zone {zone}: IsEqBypassEnabled not reflected as True: "
                f"{za.get('IsEqBypassEnabled')}"
            )
            assert abs(bypassed - flat) <= BYPASS_TOLERANCE_DB, (
                f"Zone {zone} ({output_name}): zone bypass ON — "
                f"output should return near flat ({BYPASS_TOLERANCE_DB} dB tolerance), "
                f"flat={flat:.2f}, bypassed={bypassed:.2f}, delta={bypassed - flat:.2f} dB"
            )

            # Bypass OFF → EQ should restore
            cresnext.set_zone_audio(zone, IsEqBypassEnabled=False)
            restored = self._measure(dsp, output_name, test_settings)
            za = cresnext.get_zone_audio(zone)
            assert za.get("IsEqBypassEnabled") is False, (
                f"Zone {zone}: IsEqBypassEnabled not reflected as False: "
                f"{za.get('IsEqBypassEnabled')}"
            )
            assert restored >= flat + MIN_BOOST_DB * 0.5, (
                f"Zone {zone} ({output_name}): zone bypass OFF — EQ should restore, "
                f"flat={flat:.2f}, restored={restored:.2f}, delta={restored - flat:.2f} dB"
            )
        finally:
            if sig_ch is not None:
                self._flat_band(cresnext, zone)
                dsp.stop_tone(sig_ch)

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_band_bypass_cancels_eq(self, dsp, cresnext, device_cfg, test_settings, zone):
        """
        Eq Band Bypass Test from EQ-Speaker sheets:
          1. Apply PEQ-1 boost on Band01 (EQ +10 dB@2 kHz).  Verify it is active.
          2. Band01.IsEqBypassEnabled=True  → output returns near flat (AP: Flat limits).
             CresNext band readback must reflect True.
          3. Band01.IsEqBypassEnabled=False → EQ is restored (AP: PEq-1 limits).
             CresNext band readback must reflect False.
        """
        sig_ch = None
        try:
            sig_ch, output_name = self._setup_zone(
                dsp, cresnext, device_cfg, test_settings, zone, 2000
            )
            self._flat_band(cresnext, zone)
            flat = self._measure(dsp, output_name, test_settings)
            assert flat > test_settings["mute_floor_db"], (
                f"Zone {zone}: no signal at flat baseline — {flat:.2f} dB"
            )

            # Activate EQ on Band01
            self._apply_peq(cresnext, zone, eq_type="EQ")
            active = self._measure(dsp, output_name, test_settings)
            assert active >= flat + MIN_BOOST_DB * 0.5, (
                f"Zone {zone}: EQ not active before band bypass test — "
                f"flat={flat:.2f}, active={active:.2f} dB"
            )

            # Band01 bypass ON → should return to flat
            cresnext.set_peq_band(zone, self._BAND, IsEqBypassEnabled=True)
            bypassed = self._measure(dsp, output_name, test_settings)
            band = cresnext.get_peq_band(zone, self._BAND)
            assert band.get("IsEqBypassEnabled") is True, (
                f"Zone {zone} Band01: IsEqBypassEnabled not reflected as True: "
                f"{band.get('IsEqBypassEnabled')}"
            )
            assert abs(bypassed - flat) <= BYPASS_TOLERANCE_DB, (
                f"Zone {zone} ({output_name}): Band01 bypass ON — "
                f"output should return near flat ({BYPASS_TOLERANCE_DB} dB tolerance), "
                f"flat={flat:.2f}, bypassed={bypassed:.2f}, delta={bypassed - flat:.2f} dB"
            )

            # Band01 bypass OFF → EQ should restore
            cresnext.set_peq_band(zone, self._BAND, IsEqBypassEnabled=False)
            restored = self._measure(dsp, output_name, test_settings)
            band = cresnext.get_peq_band(zone, self._BAND)
            assert band.get("IsEqBypassEnabled") is False, (
                f"Zone {zone} Band01: IsEqBypassEnabled not reflected as False: "
                f"{band.get('IsEqBypassEnabled')}"
            )
            assert restored >= flat + MIN_BOOST_DB * 0.5, (
                f"Zone {zone} ({output_name}): Band01 bypass OFF — EQ should restore, "
                f"flat={flat:.2f}, restored={restored:.2f}, delta={restored - flat:.2f} dB"
            )
        finally:
            if sig_ch is not None:
                self._flat_band(cresnext, zone)
                dsp.stop_tone(sig_ch)

    # ==================================================================
    # Zone-1 only: EQ-LineOutBypass sheet
    # ==================================================================

    def test_lineout_eq_bypass(self, dsp, cresnext, device_cfg, test_settings):
        """
        EQ-LineOutBypass sheet: IsLineOutEqBypassEnabled on Zone 1.

        The line-output EQ bypass is an INDEPENDENT bypass from the amp-output
        EQ.  With Band01 boost active, enabling IsLineOutEqBypassEnabled must
        NOT affect the amp output (A1L) — the amp path continues to show the
        boost.  Verifies that the property is accepted by CresNext and that amp
        and line-out EQ paths are independent.
        """
        sig_ch = None
        zone = 1
        try:
            sig_ch, output_name = self._setup_zone(
                dsp, cresnext, device_cfg, test_settings, zone, 2000
            )
            self._flat_band(cresnext, zone)
            flat = self._measure(dsp, output_name, test_settings)
            assert flat > test_settings["mute_floor_db"], (
                f"Zone 1: no signal at flat baseline — {flat:.2f} dB"
            )

            # Activate PEQ boost on Band01
            self._apply_peq(cresnext, zone, eq_type="EQ")
            active_amp = self._measure(dsp, output_name, test_settings)
            assert active_amp >= flat + MIN_BOOST_DB * 0.5, (
                f"Zone 1: EQ boost not active before LineOut bypass test — "
                f"flat={flat:.2f}, active={active_amp:.2f} dB"
            )

            # Enable line-out EQ bypass — amp path must NOT change
            cresnext.set_zone_audio(zone, IsLineOutEqBypassEnabled=True)
            amp_with_lineout_bypass = self._measure(dsp, output_name, test_settings)
            za = cresnext.get_zone_audio(zone)
            assert za.get("IsLineOutEqBypassEnabled") is True, (
                f"IsLineOutEqBypassEnabled not reflected as True: "
                f"{za.get('IsLineOutEqBypassEnabled')}"
            )
            # Amp output must still be boosted (line-out bypass is independent)
            assert amp_with_lineout_bypass >= flat + MIN_BOOST_DB * 0.5, (
                f"Zone 1 ({output_name}): IsLineOutEqBypassEnabled=True incorrectly "
                f"affected the amp output — flat={flat:.2f}, "
                f"amp_with_lineout_bypass={amp_with_lineout_bypass:.2f} dB"
            )

            # Disable line-out bypass and verify readback
            cresnext.set_zone_audio(zone, IsLineOutEqBypassEnabled=False)
            za = cresnext.get_zone_audio(zone)
            assert za.get("IsLineOutEqBypassEnabled") is False, (
                f"IsLineOutEqBypassEnabled not reflected as False: "
                f"{za.get('IsLineOutEqBypassEnabled')}"
            )
        finally:
            if sig_ch is not None:
                self._flat_band(cresnext, zone)
                cresnext.set_zone_audio(zone, IsLineOutEqBypassEnabled=False)
                dsp.stop_tone(sig_ch)

    # ==================================================================
    # Parameter boundary tests — Zone 1 only
    # ==================================================================

    def test_eq_max_gain_affects_output(self, dsp, cresnext, device_cfg, test_settings):
        """
        Maximum Gain=+200 (+20 dB) boosts and Gain=-200 (-20 dB) cuts the Zone 1
        DSP output at 2 kHz.  Both values must be accepted by CresNext and must
        produce measurable audio path changes ≥ MIN_BOOST_DB.
        """
        sig_ch = None
        zone = 1
        try:
            sig_ch, output_name = self._setup_zone(
                dsp, cresnext, device_cfg, test_settings, zone, 2000, tone_gain_db=-30
            )
            self._flat_band(cresnext, zone)
            baseline = self._measure(dsp, output_name, test_settings)
            assert baseline > test_settings["mute_floor_db"], "No signal at baseline"

            # Max boost: Gain=200 (+20 dB)
            self._apply_peq(cresnext, zone, eq_type="EQ", Gain=200)
            band = cresnext.get_peq_band(zone, self._BAND)
            assert band.get("Gain") == 200, (
                f"Gain=200 not reflected: {band.get('Gain')}"
            )
            max_boost = self._measure(dsp, output_name, test_settings)
            assert max_boost > baseline + MIN_BOOST_DB, (
                f"Gain=200 (+20 dB): insufficient boost — "
                f"baseline={baseline:.2f}, boosted={max_boost:.2f}, "
                f"delta={max_boost - baseline:.2f} dB"
            )

            # Max cut: Gain=-200 (-20 dB)
            self._flat_band(cresnext, zone)
            self._apply_peq(cresnext, zone, eq_type="EQ", Gain=-200)
            band = cresnext.get_peq_band(zone, self._BAND)
            assert band.get("Gain") == -200, (
                f"Gain=-200 not reflected: {band.get('Gain')}"
            )
            max_cut = self._measure(dsp, output_name, test_settings)
            assert max_cut < baseline - MIN_BOOST_DB, (
                f"Gain=-200 (-20 dB): insufficient cut — "
                f"baseline={baseline:.2f}, cut={max_cut:.2f}, "
                f"delta={max_cut - baseline:.2f} dB"
            )
        finally:
            if sig_ch is not None:
                self._flat_band(cresnext, zone)
                dsp.stop_tone(sig_ch)

    @pytest.mark.parametrize("freq", [20, 125, 1000, 8000, 20000])
    def test_eq_frequency_accepted(self, dsp, cresnext, device_cfg, test_settings, freq):
        """Frequency parameter across the full 20–20000 Hz range is accepted."""
        cresnext.set_peq_band(1, self._BAND, Frequency=freq)
        time.sleep(0.3)
        band = cresnext.get_peq_band(1, self._BAND)
        assert band.get("Frequency") == freq, (
            f"Frequency={freq} not reflected: got {band.get('Frequency')}"
        )
        cresnext.set_peq_band(1, self._BAND, Frequency=BAND_DEFAULT["Frequency"])

    @pytest.mark.parametrize("bw", [10, 33, 100, 200, 400])
    def test_eq_bandwidth_accepted(self, dsp, cresnext, device_cfg, test_settings, bw):
        """Bandwidth parameter across the valid 10–400 (0.10–4.00 oct) range is accepted."""
        cresnext.set_peq_band(1, self._BAND, Bandwidth=bw)
        time.sleep(0.3)
        band = cresnext.get_peq_band(1, self._BAND)
        assert band.get("Bandwidth") == bw, (
            f"Bandwidth={bw} not reflected: got {band.get('Bandwidth')}"
        )
        cresnext.set_peq_band(1, self._BAND, Bandwidth=BAND_DEFAULT["Bandwidth"])

    def test_multi_band_eq_audio(self, dsp, cresnext, device_cfg, test_settings):
        """
        Multiple EQ bands configured simultaneously all readback correctly and
        their combined audio effect is measurable at Zone 1 / A1L output.

        Band01: EQ +10 dB@2 kHz, Band05: EQ +5 dB@2 kHz.
        Combined boost at 2 kHz must exceed MIN_BOOST_DB vs flat baseline.
        """
        sig_ch = None
        zone = 1
        try:
            sig_ch, output_name = self._setup_zone(
                dsp, cresnext, device_cfg, test_settings, zone, 2000
            )
            # Reset bands 1 and 5 to flat
            cresnext.set_peq_band(zone, 1, **BAND_DEFAULT)
            cresnext.set_peq_band(zone, 5, **BAND_DEFAULT)
            cresnext.set_zone_audio(zone, IsEqBypassEnabled=False)
            baseline = self._measure(dsp, output_name, test_settings)
            assert baseline > test_settings["mute_floor_db"], "No signal at baseline"

            # Activate two bands simultaneously
            cresnext.set_peq_band(zone, 1,
                                  Type="EQ", Gain=100, Frequency=2000,
                                  Bandwidth=100, IsEqBypassEnabled=False)
            cresnext.set_peq_band(zone, 5,
                                  Type="EQ", Gain=50, Frequency=2000,
                                  Bandwidth=100, IsEqBypassEnabled=False)

            # CresNext readback for both bands
            band1 = cresnext.get_peq_band(zone, 1)
            band5 = cresnext.get_peq_band(zone, 5)
            assert band1.get("Gain") == 100, f"Band01 Gain readback: {band1.get('Gain')}"
            assert band5.get("Gain") == 50,  f"Band05 Gain readback: {band5.get('Gain')}"

            # Audio path: combined boost at 2 kHz
            combined = self._measure(dsp, output_name, test_settings)
            delta = combined - baseline
            assert delta >= MIN_BOOST_DB, (
                f"Multi-band EQ (Band01=+10 dB, Band05=+5 dB at 2 kHz): "
                f"expected delta ≥ {MIN_BOOST_DB} dB, "
                f"baseline={baseline:.2f}, combined={combined:.2f}, delta={delta:.2f} dB"
            )
        finally:
            if sig_ch is not None:
                for b in (1, 5):
                    cresnext.set_peq_band(zone, b, **BAND_DEFAULT)
                cresnext.set_zone_audio(zone, IsEqBypassEnabled=False)
                dsp.stop_tone(sig_ch)
