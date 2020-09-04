# -*- coding: utf-8 -*-
#
# Copyright (C) 2020 Tuono, Inc.
# All Rights Reserved
#
from noaa_sdk import noaa


class Weather(object):
    """
    Example that reaches out to a third party through an imported
    package.  Helps demonstrate techniques for interposing a third
    party service instead of using mocks.
    """

    def __init__(self):
        self.noaa = noaa.NOAA()

    def print_forecast(
        self, postal_code: str, country_code: str, hourly: bool, maximum: int
    ):
        """
        Show the forecast for a postal code, country code.
        """
        forecasts = self.noaa.get_forecasts(postal_code, country_code, hourly)
        forecasts = forecasts[0:maximum]
        for forecast in forecasts:
            print(forecast)
