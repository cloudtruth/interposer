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
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Union
from unittest import TestCase
from unittest.mock import patch

import wrapt

from interposer import CallBypass
from interposer import CallContext
from interposer import CallHandler
from interposer import Interposer
from interposer.tapedeck import Mode
from interposer.tapedeck import TapeDeck


class RecordedTestCase(TestCase):
    """
    Automatically configures a test case for recording or playback and
    giving it a tapedeck attribute.

    Calls will be placed into different channels which allows the recording
    file to contain multiple call streams.  This allows multiple unit
    tests in a test case to share the same recording file.  This technique
    is compatible with distributed test harnesses like pytest-xdist as
    long as all the tests in a test case are executed together.

    Use the @recorded decorator to make it easy to patch things for recording.

    When the environment variable RECORDING is set, the tests in this test
    class will record what they do.  When the environment variable is not
    set, the tests run in playback mode.

    NOTDONE (and maybe not necessary):
    When the environment variable RECORDING_KEY is set, the recording is
    encrypted and decrypted using the given key.  This is optional depending
    on whether the recording has secrets in it.  When dealing with third party
    packages that use tokens, they usually do.
    """

    # the name of the directory created alongside the test script
    TAPE_DIRECTORY_NAME: str = "tapes"

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
        recordings = Path(module.__file__).parent / cls.TAPE_DIRECTORY_NAME / testname

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

    def redact(self, secret: str) -> str:
        """
        Redact a secret in playback mode, and keep track of the secret in
        recording mode.  This allows tests to use secrets quite normally.
        Callers just have to remember to run secrets through redact().
        """
        return self.tapedeck.redact(secret)


class TapeDeckCallHandler(CallHandler):
    """
    A call handler that leverages the built-in tapedeck to record
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

    @staticmethod
    def isrecorded(context: CallContext) -> bool:
        """ Determines if the call is or should be recorded. """
        return context.meta.get("_handler", {}).get("record", True)

    @staticmethod
    def norecord(context: CallContext) -> None:
        """
        By default calls are recorded; this disables it.

        This should be done in on_call_begin so that it applies to both
        playback and recording mode; if you are skipping a call in recording
        then you want to skip playing it back too and call the actual call
        instead.
        """
        context.meta.setdefault("_handler", {})["record"] = False

    def on_call_begin(self, context: CallContext) -> Optional[CallBypass]:
        """
        Handle a call in playback mode.
        """
        if self._self_deck.mode == Mode.Playback and self.isrecorded(context):
            # playback raises an exception if one was recorded
            result = self._self_deck.playback(context, channel=self._self_channel)
            return CallBypass(result)

    def on_call_end_exception(self, context: CallContext, ex: Exception) -> None:
        """
        Record an exception.

        We can end up in this code path on playback if a handler sets norecord,
        as that instructs playback mode not to bypass the call.
        """
        if self.isrecorded(context):
            self._self_deck.record(context, None, ex, channel=self._self_channel)

    def on_call_end_result(self, context: CallContext, result: Any) -> Any:
        """
        Record a result.

        We can end up in this code path on playback if a handler sets norecord,
        as that instructs playback mode not to bypass the call.
        """
        if self.isrecorded(context):
            self._self_deck.record(context, result, None, channel=self._self_channel)
        return result


def recorded(
    *,
    patches: Dict[str, Any],
    prehandlers: Union[CallHandler, List[CallHandler]] = list(),
    posthandlers: Union[CallHandler, List[CallHandler]] = list(),
) -> Callable:
    """
    Closure to define a test method decorator that will record to a channel.

    This patches each key of the captures dictionary with a directive to
    instantiate a new Interposer around the value that uses the handler_cls
    to process each call.

    This decorator can be used on a RecordedTestCase test.

    Keyword Arguments:
        patches (dict): Each key is a string you would normally use with
                        patch() and the value is the actual class it will
                        eventually call.
        prehandlers (list): call handlers to run before the tape deck handler
                            that gets added automatically
        posthandlers (list): call handlers to run after the tape deck handler
                             that gets added automatically
    """

    @wrapt.decorator
    def recorded_channel(testmethod, testcase, args, kwargs):
        pre_handlers = prehandlers if isinstance(prehandlers, list) else [prehandlers]
        post_handlers = (
            posthandlers if isinstance(posthandlers, list) else [posthandlers]
        )
        channel = testmethod.__name__
        deck_handler = TapeDeckCallHandler(testcase.tapedeck, channel=channel)
        call_handlers = pre_handlers + [deck_handler] + post_handlers
        with ExitStack() as evil:
            for patched in list(patches.keys()):
                patchee = patches[patched]
                evil.enter_context(
                    patch(patched, new=Interposer(patchee, call_handlers))
                )
            return testmethod(*args, **kwargs)

    return recorded_channel
