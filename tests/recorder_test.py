# -*- coding: utf-8 -*-
#
# Copyright (C) 2020 Tuono, Inc.
# All Rights Reserved
#
import os
import uuid

from pathlib import Path
from unittest.mock import patch

from noaa_sdk import noaa

from interposer import Interposer
from interposer.example.weather import Weather
from interposer.recorder import RecordedTestCase
from interposer.recorder import TapeDeckCallHandler
from interposer.tapedeck import Mode


class TestRecordedTestCase(RecordedTestCase):
    """
    This is not a representative way to use RecordedTestCase.
    This code makes some assumptions and violates containment so it
    can go from recording to playback mode in the same test, which is
    not a supported use case, but helps to test the actual implementation.
    """

    @classmethod
    def setUpClass(cls) -> None:
        """
        Set the recording environment variable because we record first.
        """
        os.environ["RECORDING"] = "1"
        super().setUpClass()

    @classmethod
    def tearDownClass(cls) -> None:
        """
        Delete the recording file since we tested both modes in one test.
        """
        datafile = Path(str(cls.tapedeck.deck) + ".gz")
        super().tearDownClass()
        if datafile.exists():
            datafile.unlink()
        os.environ.pop("RECORDING")

    @patch("noaa_sdk.util.time")
    @patch("noaa_sdk.util.requests")
    def test_prove_noaa_sdk_uses_requests(self, mock_requests, mock_time):
        """
        This is just to prove noaa_sdk uses requests to get content.
        We need this proof in order to prove something later on.
        """
        mock_requests.get.side_effect = LookupError("proven!")
        uut = Weather()
        with self.assertRaises(Exception):
            # noaa_sdk raises Exception directly, unfortunately...
            uut.print_forecast("01001", "US", False, 3)

    def test_testcase_record_playback(self):
        """
        Tests recording and playback.

        The recording part is fairly generic.  The playback stuff is
        not representative of normal use.  One would normally control
        whether a test was recording or playing back by setting the
        RECORDING environment variable.
        """
        # self.tapedeck is set up by the fixture
        assert self.tapedeck.mode == Mode.Recording

        # the channel name is our test method name
        channel = self.id().split(".")[-1]

        # we want to record the interactions our Weather class has with
        # the third-party package it uses, noaa.  The responses from noaa
        # are pretty complex and mocking those responses would be tedious.
        with patch(
            "interposer.example.weather.noaa",
            new=Interposer(noaa, TapeDeckCallHandler(self.tapedeck, channel=channel)),
        ):
            uut = Weather()
            assert len(uut.forecast("01001", "US", False, 3)) == 3
            with self.assertRaises(Exception):
                uut.forecast("99999", "ZZ", False, 1)

        # call 0: NOAA()
        # call 1: 1st forecast()
        # call 2: 2nd forecast()
        # ordinal is left at the latest call ordinal
        assert self.tapedeck._call_ordinals[channel] == 2

        """
        This next part is not typical usage.  Normally you run the test with
        RECORDING set in the environment, and then you run the test again
        without that environment variable to play it back.
        """
        self.tapedeck.close()
        self.tapedeck.mode = Mode.Playback
        self.tapedeck.open()

        # The noaa-sdk library uses `requests` (proven above) so while we are
        # using playback mode, let's also patch requests to prove that
        # it never gets called, and this prove we're playing back responses
        # from the recording we made above
        with patch("noaa_sdk.util.requests") as mock_requests:
            with patch(
                "interposer.example.weather.noaa",
                new=Interposer(
                    noaa,
                    TapeDeckCallHandler(self.tapedeck, channel=channel),
                ),
            ):
                uut = Weather()
                assert len(uut.forecast("01001", "US", False, 3)) == 3
                with self.assertRaises(Exception):
                    uut.forecast("99999", "ZZ", False, 1)

        # prove: we never ended up calling requests
        mock_requests.assert_not_called()

        # put it back into Recording mode so the fixture can clean up
        self.tapedeck.close()
        self.tapedeck.mode = Mode.Recording
        self.tapedeck.open()

    def test_cannot_pickle(self):
        """
        Tests the _advance logic when presented with an unpicklable call.

        The code falls back to sanitizing a repr() of the call instead, which
        is still unique enough for most cases but we lose the ability to
        distinguish different objects of the same type based on their
        attributes.

        The call is to an Interposer(uuid) due to the patching and the
        TapeDeck will try to pickle it, fail, and fall back to a repr.
        """
        with patch(
            "uuid.uuid4",
            new=Interposer(
                uuid.uuid4, TapeDeckCallHandler(self.tapedeck, "test_cannot_pickle")
            ),
        ):
            assert len(str(uuid.uuid4())) == 36
