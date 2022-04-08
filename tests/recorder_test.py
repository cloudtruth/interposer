# -*- coding: utf-8 -*-
#
# Copyright (C) 2020 Tuono, Inc.
# Copyright (C) 2021 - 2022 CloudTruth, Inc.
#
import gzip
import os
import uuid
from pathlib import Path
from typing import Any
from typing import Optional
from unittest.mock import patch

from noaa_sdk import noaa

from interposer import CallBypass
from interposer import CallContext
from interposer import CallHandler
from interposer import Interposer
from interposer import isinterposed
from interposer.example.weather import Weather
from interposer.recorder import RecordedTestCase
from interposer.recorder import TapeDeckCallHandler
from interposer.tapedeck import Mode
from interposer.tapedeck import RecordedCallNotFoundError


class SomeClass(object):
    def times_two(self, value: int):
        return value * 2

    def raise_exception(self):
        raise ValueError(42)


class DoNotRecordCallHandler(CallHandler):
    """
    Tells the framework not to record almost anything.
    """

    def on_call_end_result(self, context: CallContext, result: Any) -> Any:
        if result == 42:
            TapeDeckCallHandler.norecord(context)
        return result

    def on_call_end_exception(
        self, context: CallContext, ex: Exception
    ) -> Optional[Exception]:
        TapeDeckCallHandler.norecord(context)
        return None


class RewrapCallHandler(CallHandler):
    """
    Tells the framework to rewrap everything it sees.
    """

    def on_call_begin(self, context: CallContext) -> Optional[CallBypass]:
        context.rewrap = True
        return None


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

        # pre-create a recording file that the setup code will unlink (for coverage)
        recordings = Path(__file__).parent / cls.TAPE_DIRECTORY_NAME / "recorder_test"
        recordings.mkdir(parents=True, exist_ok=True)
        recording = recordings / "TestRecordedTestCase.db"
        recording.touch(exist_ok=False)
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
        self.assertEqual(self.tapedeck.mode, Mode.Recording)

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
            self.assertEqual(len(uut.forecast("01001", "US", False, 3)), 3)
            with self.assertRaises(Exception):
                uut.forecast("99999", "ZZ", False, 1)

        # call 0: NOAA()
        # call 1: 1st forecast()
        # call 2: 2nd forecast()
        # ordinal is left at the latest call ordinal
        self.assertEqual(self.tapedeck._call_ordinals[channel], 2)

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
                self.assertEqual(len(uut.forecast("01001", "US", False, 3)), 3)
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

        The code uses a repr() of the call which is still unique enough
        for most cases but we lose the ability to discriminate between
        objects of the same type with different contents, however when the
        goal is to record API interactions, what's in the API call is
        typically only what matters as services are mostly stateless.
        """
        with patch(
            "uuid.uuid4",
            new=Interposer(
                uuid.uuid4, TapeDeckCallHandler(self.tapedeck, "test_cannot_pickle")
            ),
        ):
            self.assertEqual(len(str(uuid.uuid4())), 36)

    def test_selective_recording(self) -> None:
        """
        Tests ability to selectively record.
        """
        # self.tapedeck is set up by the fixture
        self.assertEqual(self.tapedeck.mode, Mode.Recording)

        uut = Interposer(
            SomeClass(),
            handlers=[
                DoNotRecordCallHandler(),
                TapeDeckCallHandler(self.tapedeck, "test_selective_recording"),
            ],
        )

        # we will make three calls, but only one will record; if all of them
        # were to record the ordinal count for the channel would be at 2 (0, 1, 2)

        self.assertIsNone(self.tapedeck._call_ordinals.get("test_selective_recording"))
        self.assertEqual(uut.times_two(21), 42)  # when result is 42 recording disabled
        self.assertIsNone(self.tapedeck._call_ordinals.get("test_selective_recording"))
        self.assertEqual(uut.times_two(42), 84)  # this one advances to ordinal zero
        self.assertEqual(
            self.tapedeck._call_ordinals.get("test_selective_recording"), 0
        )
        with self.assertRaises(ValueError):
            uut.raise_exception()  # no exceptions are being recorded
        self.assertEqual(
            self.tapedeck._call_ordinals.get("test_selective_recording"), 0
        )

    def test_selective_rewrap(self) -> None:
        """
        Tests ability to selectively rewrap result even during playback.
        """
        # self.tapedeck is set up by the fixture
        self.assertEqual(self.tapedeck.mode, Mode.Recording)

        uut = Interposer(
            SomeClass(),
            handlers=[
                RewrapCallHandler(),
                TapeDeckCallHandler(self.tapedeck, "test_selective_rewrap"),
            ],
        )

        # is it rewrapped after recording?
        self.assertTrue(isinterposed(uut.times_two(21)))

        self.tapedeck.close()
        self.tapedeck.mode = Mode.Playback
        self.tapedeck.open()

        uut = Interposer(
            SomeClass(),
            handlers=[
                RewrapCallHandler(),
                TapeDeckCallHandler(self.tapedeck, "test_selective_rewrap"),
            ],
        )

        # is it rewrapped, even during playback?
        self.assertTrue(isinterposed(uut.times_two(21)))

        # put it back into Recording mode so the fixture can clean up
        self.tapedeck.close()
        self.tapedeck.mode = Mode.Recording
        self.tapedeck.open()


class HolderOfFineSecrets(object):
    """
    Tests call argument, recorded results.
    """

    def __init__(self, token: str):
        self.token = token

    def get_token(self) -> str:
        return self.token


class SecretsTestCase(RecordedTestCase):
    """
    Tests the secret redaction capability.
    """

    token = "6effb02c-f1f7-4f07-bdc6-eef14e4efba5"  # nosec

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
        redactions = cls.tapedeck._redactions
        super().tearDownClass()
        if datafile.exists():
            with gzip.open(datafile, "rb") as fin:
                raw = fin.read()
                for secret, replacement in redactions.items():
                    assert (  # nosec
                        isinstance(secret, bytes) and secret not in raw
                    ) or (
                        isinstance(secret, str) and secret.encode() not in raw
                    ), "a secret leaked into the recording!"
            datafile.unlink()
        os.environ.pop("RECORDING")

    def test_secrets(self):
        """
        In recording mode, redact() keeps track of the secret and returns it
        for use by the caller so the live testing works.  At the end of
        recording the test fixture removes the secrets from the recording,
        replacing them with redactions (all carats).

        In playback mode, redact() converts the secret to all carats, so the
        calls with the secret as an argument can be found.
        """
        # here's our "secret"
        # wrap the class
        cls = Interposer(
            HolderOfFineSecrets,
            handlers=TapeDeckCallHandler(self.tapedeck, self.id().split(".")[-1]),
        )
        # instantiate the class using a *gasp* secret
        # in recording mode this passes the secret through and adds it to a
        # post-processing redaction list and after the recording file is closed
        # the secrets get redacted; in playback mode this redacts it immediately
        # so the playback matches the recording
        self.assertFalse(self.tapedeck._redactions)
        uut = cls(self.redact(self.token, "TOKEN"))
        self.assertTrue(self.tapedeck._redactions)
        self.assertEqual(uut.get_token(), self.redact(self.token, "TOKEN2"))

        self.tapedeck.close()  # applies redaction to recording
        self.tapedeck.mode = Mode.Playback
        self.tapedeck.open()

        self.assertFalse(self.tapedeck._redactions)
        uut = cls(self.redact("foo", "TOKEN"))
        foo = self.redact("foo", "TOKEN")
        self.assertEqual(foo, "TOKEN_______________________________")

        # most importantly, the object initializer argument was redacted
        self.assertEqual(uut.get_token(), foo)
        with self.assertRaises(RecordedCallNotFoundError):
            uut.get_token()

        # put it back into Recording mode so the fixture can clean up
        self.tapedeck.close()
        self.tapedeck.mode = Mode.Recording
        self.tapedeck.open()
