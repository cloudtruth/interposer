# -*- coding: utf-8 -*-
#
# Copyright (C) 2020 Tuono, Inc.
# All Rights Reserved
#
import logging
import os
import shutil
import tempfile

from pathlib import Path
from unittest.mock import patch

from noaa_sdk import noaa

from interposer import Interposer
from interposer import Mode
from interposer._testing.weather import Weather
from interposer.testcase import InterposedTestCase


class TestInterposedTestCase(InterposedTestCase):
    """
    This is a test of the testcase code.  The test for recording
    is a decent example of how to inject the interposer to record
    a third party module's interactions.

    Given this is a unit test for the test case fixture then this
    test is going to modify the environment variables directly.
    Normally you would run a test with RECORDING=1 set, which saves
    a database containing the interaction, then re-run the test
    without RECORDING=1 set and it plays things back.

    This test must run serially on the same system.
    """

    def setUpClass() -> None:
        """
        To test recording we need to set an environment variable.
        """
        os.environ["RECORDING"] = "1"

    def setUp(self, *args, **kwargs) -> None:
        """
        Set up our recording directory.
        """
        self.recordings = Path(tempfile.mkdtemp())
        super().setUp(*args, recordings=self.recordings, **kwargs)
        self.interposer.logger.setLevel(logging.DEBUG)

    def tearDown(self):
        """
        Clean up the temporary directory.
        """
        shutil.rmtree(str(self.recordings))

    @patch("noaa_sdk.util.requests")
    @patch("noaa_sdk.util.time")
    def test_prove_noaa_sdk_uses_requests(self, mock_requests, mock_time):
        """
        This is just an additional proof to show noaa_sdk uses
        requests to get stuff.  We assume this to prove something
        later on.
        """
        mock_requests.get.side_effect = LookupError("proven!")
        uut = Weather()
        with self.assertRaises(Exception):
            # noaa_sdk raises Exception directly, unfortunately...
            uut.print_forecast("11365", "US", False, 3)

    def test_testcase_record_playback(self):
        """
        Tests the InterposedTestCase behavior and shows how to inject
        the interposer for test purposes.
        """
        assert self.mode == Mode.Recording

        # we want to record the interactions our Weather class has with
        # the third-party package it uses, noaa.  The responses from noaa
        # are pretty complex and mocking those responses would be tedious.
        with patch("interposer._testing.weather.noaa", new=self.interposer.wrap(noaa)):
            uut = Weather()
            uut.print_forecast("11365", "US", False, 3)

        """
        This next part is really just to prove that InterposedTestCase is actually
        causing Weather to avoid calling noaa, and instead play back responses
        that were recorded.  You would not normally have a separate record and
        playback test in your interposer-enabled tests, but instead manually
        run with RECORDING=1 in your environment, generating a recording file,
        and then when you run the test again without RECORDING set in the
        environment, that recording file gets played back.

        This is not intended to be an example.
        """
        super().tearDown()
        self.interposer.close()
        self.mode = Mode.Playback
        os.environ.pop("RECORDING")
        super().setUp(recordings=self.recordings)
        self.interposer = Interposer(self.tape, self.mode)
        self.interposer.open()

        # The noaa-sdk library uses `requests` (proven above) so while we are
        # using playback mode, let's also patch requests to prove that
        # it never gets called, and this prove we're playing back responses
        # from the recording we made above
        with patch("noaa_sdk.util.requests") as mock_requests:
            with patch(
                "interposer._testing.weather.noaa", new=self.interposer.wrap(noaa)
            ):
                uut = Weather()
                uut.print_forecast("11365", "US", False, 3)

        mock_requests.assert_not_called()
