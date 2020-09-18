# -*- coding: utf-8 -*-
#
# Copyright (C) 2019 - 2020 Tuono, Inc.
# All Rights Reserved
#
import logging
import os
import pickle  # nosec
import shutil
import tempfile
import uuid

from datetime import datetime
from hashlib import sha256
from pathlib import Path
from unittest import TestCase

from interposer import CallContext
from interposer.tapedeck import Mode
from interposer.tapedeck import RecordedCallNotFoundError
from interposer.tapedeck import RecordingTooOldError
from interposer.tapedeck import TapeDeck
from interposer.tapedeck import TapeDeckOpenError


class SomeClass(object):
    def __init__(self, thing: object):
        self.logger = logging.getLogger(__name__)
        self.thing = thing

    def amethod(self) -> str:
        return uuid.uuid4()


class TapeDeckTest(TestCase):
    def setUp(self):
        self.datadir = Path(tempfile.mkdtemp())
        self.someclass = SomeClass("foo")
        self.context1 = CallContext(
            call=self.someclass.amethod,
            args=(
                42,
                SomeClass(datetime.utcnow()),
            ),
            kwargs={"chuck": "jerk", "castiel": "grumbly"},
        )
        self.context2 = CallContext(
            call=self.someclass.amethod,
            args=(),
            kwargs={},
        )

    def tearDown(self):
        shutil.rmtree(str(self.datadir))

    def test_pickle_method_idempotent(self):
        """
        This proves pickling two methods in two different objects will not
        be different because of the memory address, which is an assumption
        the tape deck relies upon.

        It also shows that the content of the class enclosing the method is
        also taken into account, so if that class is configured differently
        then it is technically a different call.

        NOTE: We may need to relax this if it proves to be too strict, and
        just use the repr(context.call) with the memory addresses stripped out.
        """
        someotherclass = SomeClass("foo")

        raw = pickle.dumps(self.context1, protocol=TapeDeck.PICKLE_PROTOCOL)
        uniq = sha256(raw)
        result1 = uniq.hexdigest()

        self.context1.call = someotherclass.amethod
        raw2 = pickle.dumps(self.context1, protocol=TapeDeck.PICKLE_PROTOCOL)
        uniq2 = sha256(raw2)
        result2 = uniq2.hexdigest()

        # proves the same method call on a class with the same configuration
        # yields the same hash
        assert result1 == result2

        somethirdclass = SomeClass("bar")  # not foo like the original

        self.context1.call = somethirdclass.amethod
        raw3 = pickle.dumps(self.context1, protocol=TapeDeck.PICKLE_PROTOCOL)
        uniq3 = sha256(raw3)
        result3 = uniq3.hexdigest()

        # proves that if the object has a different configuration it is technically
        # a different call
        assert result1 != result3

    def test_record_playback(self):
        """
        Tests basic record and playback.

        CallContext is meant for one-time use so we have to clear some meta
        from them after each use.

        We manipulate logging levels to exercise different logging paths.
        """
        with TapeDeck(self.datadir / "recording", Mode.Recording) as uut:
            uut._logger.setLevel(TapeDeck.DEBUG_WITH_RESULTS)
            # default channel
            os.environ["TAPEDECKDEBUG"] = "ON"
            uut.record(self.context1, "dean", None)
            os.environ.pop("TAPEDECKDEBUG")
            uut.record(self.context2, None, NotImplementedError("unit test error"))
            self.context1.meta.pop(TapeDeck.LABEL_TAPE)
            self.context2.meta.pop(TapeDeck.LABEL_TAPE)
            # reverse channel
            uut._logger.setLevel(logging.DEBUG)
            uut.record(
                self.context2,
                None,
                NotImplementedError("unit test error"),
                channel="reverse",
            )
            uut.record(self.context1, "dean", None, channel="reverse")
            self.context1.meta.pop(TapeDeck.LABEL_TAPE)
            self.context2.meta.pop(TapeDeck.LABEL_TAPE)

        with TapeDeck(self.datadir / "recording", Mode.Playback) as uut:
            # replay the reverse channel first proving there is no global call order
            with self.assertRaises(NotImplementedError):
                uut.playback(self.context2, channel="reverse")
            assert uut.playback(self.context1, channel="reverse") == "dean"
            self.context1.meta.pop(TapeDeck.LABEL_TAPE)
            self.context2.meta.pop(TapeDeck.LABEL_TAPE)
            # now the default channel
            uut._logger.setLevel(logging.INFO)
            assert uut.playback(self.context1) == "dean"
            with self.assertRaises(NotImplementedError):
                uut.playback(self.context2)
            self.context1.meta.pop(TapeDeck.LABEL_TAPE)
            self.context2.meta.pop(TapeDeck.LABEL_TAPE)
            # go past the last recorded call - cannot find
            with self.assertRaises(RecordedCallNotFoundError):
                uut.playback(self.context1)

    def test_open_close_twice(self):
        """ Tests calling open and close twice. """
        with TapeDeck(self.datadir / "recording", Mode.Recording) as uut:
            with self.assertRaises(TapeDeckOpenError):
                uut.open()  # 2nd time, not idempotent (works as designed)
        uut.close()  # 2nd time, idempotent

    def test_recording_too_old(self):
        """ Tests opening a file where the recording is too old. """
        with TapeDeck(self.datadir / "recording", Mode.Recording) as uut:
            uut.record(self.context1, "dean", None)
        save = TapeDeck.EARLIEST_FILE_FORMAT_SUPPORTED
        try:
            TapeDeck.EARLIEST_FILE_FORMAT_SUPPORTED = TapeDeck.CURRENT_FILE_FORMAT + 1
            with self.assertRaises(RecordingTooOldError):
                with TapeDeck(self.datadir / "recording", Mode.Playback) as uut:
                    pass
        finally:
            TapeDeck.EARLIEST_FILE_FORMAT_SUPPORTED = save
