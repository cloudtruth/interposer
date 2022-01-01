# -*- coding: utf-8 -*-
#
# Copyright (C) 2020 - 2021 Tuono, Inc.
# Copyright (C) 2021 - 2022 CloudTruth, Inc.
#
import logging

from noaa_sdk import noaa

from interposer.example.weather import Weather
from interposer.recorder import recorded
from interposer.recorder import RecordedTestCase
from interposer.tapedeck import TapeDeck


class TestWeather(RecordedTestCase):
    """Example of a record/playback aware test."""

    def setUp(self) -> None:
        """Enable logging level that shows contents of results."""
        logging.basicConfig(level=TapeDeck.DEBUG_WITH_RESULTS)
        super().setUp()

    @recorded(patches={"interposer.example.weather.noaa": noaa})
    def test_print_forecast(self) -> None:
        uut = Weather()
        self.assertEqual(len(uut.forecast("01001", "US", False, 3)), 3)
