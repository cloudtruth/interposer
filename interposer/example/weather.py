# -*- coding: utf-8 -*-
#
# Copyright (C) 2020 Tuono, Inc.
# All Rights Reserved
#
import uuid

from noaa_sdk import noaa


class Weather(object):
    """
    Example that reaches out to a third party through an imported
    package.  Helps demonstrate techniques for interposing a third
    party service instead of using mocks.
    """

    def __init__(self):
        self.noaa = noaa.NOAA()

    def forecast(self, postal_code: str, country_code: str, hourly: bool, maximum: int):
        """
        Show the forecast for a postal code, country code.
        """
        return self.noaa.get_forecasts(postal_code, country_code, hourly)[0:maximum]

    def uniq(self) -> str:
        """
        Generates a unique identity.
        """
        return str(uuid.uuid4())
