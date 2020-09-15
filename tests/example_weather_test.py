# -*- coding: utf-8 -*-
#
# Copyright (C) 2020 Tuono, Inc.
# All Rights Reserved
#
from noaa_sdk import noaa

from interposer.example.weather import Weather
from interposer.recorder import recorded
from interposer.recorder import RecordedTestCase


class TestWeather(RecordedTestCase):
    """ Example of a record/playback aware test. """

    @recorded(patches={"interposer.example.weather.noaa": noaa})
    def test_print_forecast(self) -> None:
        uut = Weather()
        assert len(uut.forecast("01001", "US", False, 3)) == 3
