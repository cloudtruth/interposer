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


class KeeperOfFineSecrets(object):
    """
    A typical object that holds a secret (token).
    """

    def __init__(self, token: str) -> None:
        self.api_key = token

    def get_token(self) -> str:
        return self.api_key


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

    def test_redact(self):
        """
        Tests logic that makes an obscure but unique redaction string.
        """
        with TapeDeck(self.datadir / "recording", Mode.Recording) as uut:
            with self.assertRaises(TypeError):
                uut.redact(None, "foo")
            with self.assertRaises(TypeError):
                uut.redact(42, "foo")
            with self.assertRaises(AttributeError):
                uut.redact("", "foo")
            with self.assertRaises(TypeError):
                uut.redact("foo", None)
            with self.assertRaises(TypeError):
                uut.redact("foo", 42)
            with self.assertRaises(AttributeError):
                uut.redact("foo", "")

            # identifier longer than secret gets clipped
            assert uut.redact("123456789", "THIS_IS_A_REDACTED_COUNT") == "123456789"
            assert uut._redactions.get("123456789") == "THIS_IS_A"

            # identifier shorter than secret gets padded
            assert uut.redact("candycane", "THIS") == "candycane"
            assert uut._redactions.get("candycane") == "THIS_____"

            with self.assertRaises(AttributeError):
                # each identifier must be unique
                uut.redact("crush", "THIS")

        with TapeDeck(self.datadir / "recording", Mode.Playback) as uut:
            # playback caller may not know the secret but does know the identifier
            assert uut.redact("foo", "THIS_IS_A_REDACTED_COUNT") == "THIS_IS_A"
            assert uut.redact("foo", "THIS") == "THIS_____"

    def test_recording_secrets(self):
        """ Tests automatic redaction of known secrets and use in playback """
        token = str(uuid.uuid4())
        token2 = str(uuid.uuid4())
        keeper = KeeperOfFineSecrets(token)

        # pretend someone created an object and made two calls where one succeeds and one raises

        with TapeDeck(self.datadir / "recording", Mode.Recording) as uut:
            use_token = uut.redact(token, "REDACTED_SMALLER_THAN_ORIGINAL")
            assert use_token == token
            use_token2 = uut.redact(
                token2, "REDACTED_LARGER_THAN_ORIGINAL_AND_THAT_IS_OKAY"
            )
            assert use_token2 == token2
            uut.record(
                CallContext(
                    call=KeeperOfFineSecrets,
                    args=(use_token,),
                    kwargs={"other": use_token2},
                ),
                keeper,
                None,
            )
            uut.record(
                CallContext(call=keeper.get_token, args=(), kwargs={}), token, None
            )
            uut.record(
                CallContext(call=keeper.get_token, args=(), kwargs={}),
                None,
                ValueError(token),
            )

            # a secret redaction identifier can only be used once in a recording
            with self.assertRaises(AttributeError):
                uut.redact("foo", "REDACTED_SMALLER_THAN_ORIGINAL")
            # but if the secret is the same that is not an error
            assert uut.redact(token, "REDACTED_SMALLER_THAN_ORIGINAL") == token

        # now during playback see everything with a secret (token) has been redacted!

        with TapeDeck(self.datadir / "recording", Mode.Playback) as uut:
            # during playback the secret passed in may not be the same as during recording
            # however since it was redacted, the identifier is what's important
            redacted_token = uut.redact(
                "not-the-original-token", "REDACTED_SMALLER_THAN_ORIGINAL"
            )
            assert redacted_token != token
            # the redaction will have the same length as the original secret
            assert len(redacted_token) == len(token)
            redacted_token2 = uut.redact(
                "not-the-original-token2",
                "REDACTED_LARGER_THAN_ORIGINAL_AND_THAT_IS_OKAY",
            )
            assert redacted_token2 != token2
            redacted_keeper = uut.playback(
                CallContext(
                    call=KeeperOfFineSecrets,
                    args=(redacted_token,),
                    kwargs={"other": redacted_token2},
                )
            )
            assert redacted_keeper.get_token() == redacted_token
            assert (
                uut.playback(
                    CallContext(call=redacted_keeper.get_token, args=(), kwargs={})
                )
                == redacted_token
            )
            with self.assertRaises(ValueError) as ex:
                assert uut.playback(
                    CallContext(call=redacted_keeper.get_token, args=(), kwargs={})
                )
            assert token not in str(ex.exception)
            assert redacted_token in str(ex.exception)
            uut.dump(self.datadir / "dump.yaml")

            # this identifier was never used during recording
            with self.assertRaises(AttributeError):
                uut.redact("foo", "NEVER_USED_DURING_RECORDING")

        # now with a misaligned playback

        with TapeDeck(self.datadir / "recording", Mode.Playback) as uut:
            with self.assertRaises(RecordedCallNotFoundError):
                uut.playback(
                    CallContext(
                        call=KeeperOfFineSecrets, args=(), kwargs={"sam": "dean"}
                    )
                )
