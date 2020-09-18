# -*- coding: utf-8 -*-
#
# Copyright (C) 2019 - 2020 Tuono, Inc.
# All Rights Reserved
#
import gzip
import inspect
import os

from contextlib import ExitStack
from pathlib import Path
from typing import Any
from typing import Dict
from typing import Optional
from unittest import TestCase
from unittest.mock import patch

import wrapt

from interposer import CallBypass
from interposer import CallContext
from interposer import CallHandler
from interposer import Interposer
from interposer.tapedeck import Mode
from interposer.tapedeck import TapeDeck


class TapeDeckCallHandler(CallHandler):
    """
    An call handler that leverages the built-in tapedeck to record
    or playback a series of calls to a module, class, object, or
    function; the tape deck mode controls the behavior.
    """

    def __init__(self, deck: TapeDeck, channel: str = "default") -> None:
        """
        Initializer.

        Arguments:
            deck (TapeDeck): location of recorded information
            channel (str): the channel name
        """
        super().__init__()
        self._self_channel = channel
        self._self_deck = deck

    def on_call_begin(self, context: CallContext) -> Optional[CallBypass]:
        """
        Handle a call in playback mode.
        """
        if self._self_deck.mode == Mode.Playback:
            # playback raises an exception if one was recorded
            return CallBypass(
                result=self._self_deck.playback(context, channel=self._self_channel)
            )

    def on_call_end_exception(self, context: CallContext, ex: Exception) -> None:
        """
        Record an exception.

        Playback bypasses the call so we never get here on playback,
        but an assert is placed for good measure.
        """
        assert self._self_deck.mode == Mode.Recording
        self._self_deck.record(context, None, ex, channel=self._self_channel)

    def on_call_end_result(self, context: CallContext, result: Any) -> Any:
        """
        Record a result.

        Playback bypasses the call so we never get here on playback,
        but an assert is placed for good measure.
        """
        assert self._self_deck.mode == Mode.Recording
        self._self_deck.record(context, result, None, channel=self._self_channel)
        return result


class RecordedTestCase(TestCase):
    """
    Enables tests to be run in a recording or playback mode.

    Calls will be placed into different channels which allows the recording
    file to contain multiple call streams.  This allows multiple unit
    tests in a test case to share the same recording file.  This technique
    is compatible with distributed test harnesses like pytest-xdist as
    long as all the tests in a test case are executed together.

    When the environment variable RECORDING is set, the tests in this test
    class will record what they do.  When the environment variable is not
    set, the tests run in playback mode.
    """

    # the name of the directory created alongside the test script
    DATA_DIRECTORY = "tapes"

    @classmethod
    def setUpClass(cls) -> None:
        """
        Prepare a tape deck for recording or playback.

        The location of the tape deck will depend on the location of the
        original test script.  A subdirectory named "tapes" is created and
        one recording file per test class is created.
        """
        super().setUpClass()

        mode = Mode.Recording if os.environ.get("RECORDING") else Mode.Playback
        module = inspect.getmodule(cls)
        testname = Path(module.__file__).stem
        recordings = Path(module.__file__).parent / "tapes" / testname

        recording = recordings / f"{cls.__name__}.db"
        if mode == Mode.Playback:
            # decompress the recording
            with gzip.open(str(recording) + ".gz", "rb") as fin:
                with recording.open("wb") as fout:
                    fout.write(fin.read())
        else:
            recordings.mkdir(parents=True, exist_ok=True)

        cls.tapedeck = TapeDeck(recording, mode)
        cls.tapedeck.open()

    @classmethod
    def tearDownClass(cls) -> None:
        """
        Finalize recording or playback.
        """
        mode = cls.tapedeck.mode
        recording = cls.tapedeck.deck
        cls.tapedeck.close()
        if mode == Mode.Recording:
            # compress the recording
            with recording.open("rb") as fin:
                with gzip.open(str(recording) + ".gz", "wb") as fout:
                    fout.write(fin.read())

        # recording is the uncompressed file - do not leave it around
        recording.unlink()

        super().tearDownClass()


def recorded(*, patches: Dict[str, Any]):
    """
    Closure to define a test method decorator that will record to a channel.

    Can be used on a RecordedTestCase test.
    """

    @wrapt.decorator
    def recorded_channel(testmethod, testcase, args, kwargs):
        channel = testmethod.__name__
        handler = TapeDeckCallHandler(testcase.tapedeck, channel=channel)
        with ExitStack() as evil:
            for patched in list(patches.keys()):
                patchee = patches[patched]
                evil.enter_context(patch(patched, new=Interposer(patchee, handler)))
            return testmethod(*args, **kwargs)

    return recorded_channel
