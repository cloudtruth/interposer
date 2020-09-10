# -*- coding: utf-8 -*-
from pathlib import Path
from unittest.mock import patch

from noaa_sdk import noaa

from interposer import InterposedTestCase
from interposer._testing.weather import Weather


class TestWeather(InterposedTestCase):
    def setUp(self) -> None:
        super().setUp(recordings=Path(__file__).parent / "tapes")

    def test_print_forecast(self) -> None:
        """
        Inserts the interposer between the importing class
        and the imported class.
        """
        with patch("interposer._testing.weather.noaa", new=self.interposer.wrap(noaa)):
            uut = Weather()
            uut.print_forecast("01886", "US", False, 3)
