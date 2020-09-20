# -*- coding: utf-8 -*-
#
# Copyright (C) 2019 - 2020 Tuono, Inc.
# All Rights Reserved
#
import logging
import os
import pickle  # nosec
import shelve

from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import auto
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any
from typing import Callable
from typing import Dict
from typing import Optional
from typing import Set

import yaml

from interposer import CallContext


class Mode(Enum):
    """
    The running mode of the tape deck.

    In Recording mode, calls get recorded.
    In Playback mode, calls get played back.
    """

    Playback = auto()
    Recording = auto()


@dataclass
class Payload:
    """
    The record for the content behind each hash.
    """

    context: CallContext
    result: Any
    ex: Exception


class TapeDeckError(RuntimeError):
    """
    Base class for tape deck errors.
    """

    pass


class RecordedCallNotFoundError(TapeDeckError):
    """
    The call specified by the context was not found.
    """

    def __init__(self, context: CallContext) -> None:
        super().__init__(f"Could not find call: {context}.  Regenerate your recording.")


class RecordingTooOldError(TapeDeckError):
    """
    The recording file is too old.
    """

    def __init__(
        self, file_format: int, earliest_format: int, latest_format: int
    ) -> None:
        super().__init__(
            f"Recording file format is too old; file={file_format}, "
            f"accepted={earliest_format}:{latest_format}"
        )


class TapeDeckOpenError(TapeDeckError):
    """
    The recording file is already open.
    """

    def __init__(self):
        super().__init__("The tape deck is already open.")


class TapeDeck(AbstractContextManager):
    """
    A pickling call recording and playback class.

    Known limitations:

    1. All arguments, results, and exceptions must be safe to pickle.
    2. Asynchronous calls have not been tested and likely will not work.
    3. The recorder does not expect to be active in multiple threads.

    By recording your interaction with an imported library, you can
    prove actual behavior occasionally, and generate a recording that
    can be used to replay the behavior later.  This allows you to run
    very accurate unit tests with data that is from the actual source
    rather than hand-produced mocks.

    Recording has advantages and disadvantages, so the right solution
    for your situation depends on many things.  Recording eliminates
    the need to produce and maintain mocks of third party libraries.
    Mocks of third party libraries that change or are not well
    understood are fragile and lead to a false sense of safety.
    Recordings on the other hand are always correct, but they need to
    be regenerated when your logic changes around the third party calls,
    or when the third party changes.

    Recording file format history:
      -  1: code did not record exceptions
      -  2: added exception recording and playback support
      -  3: renamed "context" to "channel" for compatibility with v2 recording
      -  4: ordinal counting of calls for linear playback
      -  5: support datetime and enum in argument lists
      -  6: major refactor rendered previous recordings unusable

    NOTE: We are expressly not using `dill` because it stores class
          definitions and as a result would not actually catch errors
          when a third party library is updated.
    """

    CURRENT_FILE_FORMAT = 6
    EARLIEST_FILE_FORMAT_SUPPORTED = 6
    PICKLE_PROTOCOL = 4

    LABEL_CHANNEL = "channel"
    LABEL_HASH = "hash"
    LABEL_ORDINAL = "ordinal"
    LABEL_RESULT = "result"
    LABEL_TAPE = "tape"

    LABEL_FILE_FORMAT = "_file_format"
    LABEL_VERSION = "_version"  # extant; use LABEL_FILE_FORMAT

    # a logging level lower than logging.DEBUG (10)
    DEBUG_WITH_RESULTS = 7

    def __init__(self, deck: Path, mode: Mode) -> None:
        """
        Initializer.

        Arguments:
            deck (Path): The full path to the recording filename.
            mode (Mode): The operational mode - Playback or Recording.
        """
        self.deck = deck
        self.file_format = None
        self.mode = mode
        self.redactions: Set[str] = set()

        self._logger = logging.getLogger(__name__)

        # call ordinal key (channel name) and value (ordinal number)
        self._call_ordinals: Dict[str, int] = {}

        # the open file resource
        self._tape = None

    def __enter__(self):
        """ AbstractContextManager """
        self.open()
        return self

    def __exit__(self, *exc_details):
        """ AbstractContextManager """
        self.close()

    def dump(self, outfile: Path) -> None:
        """
        Dump the database file for analysis.
        """
        results = {}
        for key in self._tape.keys():
            payload = self._tape[key]
            if len(key) != 64:
                results[key] = payload
            else:
                results.setdefault(payload.context.meta["tape"]["channel"], []).append(
                    payload
                )
        for channel in results.keys():
            if len(channel) == 64:
                results[channel] = list(
                    sorted(
                        results[channel],
                        key=lambda item: item.context.meta["tape"]["ordinal"],
                    )
                )
        with outfile.open("w") as fout:
            yaml.dump(results, fout, default_flow_style=False)

    def open(self) -> None:
        """
        Open the tape deck for recording or playback.

        Raises:
            TapeDeckOpenError if the tape deck is already open.
            RecordingTooOldError if the recording file version is not supported.
        """
        if self._tape:
            raise TapeDeckOpenError()

        if self.mode == Mode.Playback:
            self._tape = shelve.open(
                str(self.deck), flag="r", protocol=self.PICKLE_PROTOCOL
            )
            self.file_format = self._tape.get(
                self.LABEL_FILE_FORMAT, self._tape.get(self.LABEL_VERSION, 1)
            )
            if self.file_format < self.EARLIEST_FILE_FORMAT_SUPPORTED:
                raise RecordingTooOldError(
                    self.file_format,
                    self.EARLIEST_FILE_FORMAT_SUPPORTED,
                    self.CURRENT_FILE_FORMAT,
                )
        else:
            self._tape = shelve.open(
                str(self.deck), flag="c", protocol=self.PICKLE_PROTOCOL
            )
            self._tape[self.LABEL_FILE_FORMAT] = self.CURRENT_FILE_FORMAT
            self.file_format = self.CURRENT_FILE_FORMAT

        # ensure if close() then open() is called we reset the ordinals to zero
        self._call_ordinals = dict()
        self.redactions = set()

        self._call_ordinals = {}

        self._log(
            logging.DEBUG,
            "open",
            "file",
            f"{self.deck} for {self.mode} using file format {self.file_format}",
        )

    def close(self) -> None:
        """
        Close the tape deck.

        If the tape deck is not open, this does nothing.
        """
        if self._tape:  # prevents errors closing after failed open()
            self._tape.close()
            self._tape = None
            self._log(
                logging.DEBUG,
                "close",
                "file",
                f"{self.deck} for {self.mode} using file format {self.file_format}",
            )

    def record(
        self,
        context: CallContext,
        result: Any,
        ex: Optional[Exception],
        channel: str = "default",
    ) -> None:
        """
        Record a call.

        To get the result of this recording at a later time, call playback:
            playback(context)

        Args:
            context (CallContext): the call context to store
            result: The result from the call, as any python object that can be pickled
            ex: The exception that occurred as a result of the call, if any
        """
        uniq = self._advance(context, channel)

        payload = Payload(context=context, result=result, ex=ex)
        try:
            self._tape[uniq] = self._redact(payload)
        except pickle.PicklingError:
            save_call = self._reduce_call(context)
            try:
                self._tape[uniq] = self._redact(payload)
            finally:
                context.call = save_call

        if ex is None:
            self._log_result("record", context, result)
        else:
            self._log_ex("record", context, ex)

    def playback(self, context: CallContext, channel: str = "default") -> Any:
        """
        Playback a previously recorded call.

        Arguments:
            context (CallContext): the call context to retrieve
            channel (str): the channel name

        Returns:
            If an exception was not recorded for this call, the result
            that was recorded is returned.

        Raises:
            If an exception was recorded for this call, it is raised.
        """
        uniq = self._advance(context, channel)
        recorded = self._tape.get(uniq, RecordedCallNotFoundError(context))
        if isinstance(recorded, RecordedCallNotFoundError):
            raise recorded

        payload = recorded

        if payload.ex is None:
            self._log_result("playback", context, payload.result)
            return payload.result
        else:
            self._log_ex("playback", context, payload.ex)
            raise payload.ex

    def redact(self, secret: str) -> str:
        """
        Auto-track secrets for redaction.

        In recording mode this returns the secret and makes sure the secret
        never makes it into the recording; instead a redacted version does,
        which is done before call contexts get hashed so the hashed context
        is of the redacted context.  The results and exceptions are also
        redacted before storage.

        In playback mode the redacted secret is returned so the lookup finds
        the redacted context.
        """
        if self.mode == Mode.Recording:
            self.redactions.add(secret)
            return secret
        else:
            return "^" * len(secret)

    def _advance(self, context: CallContext, channel: str) -> str:
        """
        Advance to processing the next call.

        This will increment the call ordinal for the given channel and then
        hash together the channel name, call ordinal, and context to get a
        unique signature that can be used to find the call again later.
        """
        ordinal = self._call_ordinals[channel] = (
            self._call_ordinals.setdefault(channel, -1) + 1
        )
        our_meta = context.meta.setdefault(self.LABEL_TAPE, {})
        our_meta[self.LABEL_CHANNEL] = channel
        our_meta[self.LABEL_ORDINAL] = ordinal

        result = None
        try:
            # attempt to pickle the call object verbatim - this is a strong
            # guarantee of uniqueness
            result = self._hickle(context)
        except pickle.PicklingError:
            # since pickling the context with the call verbatim failed
            # fall back to using a string representation of the call
            save_call = self._reduce_call(context)
            try:
                result = self._hickle(context)
            finally:
                context.call = save_call
        our_meta[self.LABEL_HASH] = result
        return result

    def _hickle(self, context: CallContext) -> str:
        """
        Hash a context using a redacted pickle.

        Raises:
            PicklingError if something in the context cannot be pickled.
        """
        raw = self._redact(context, return_bytes=True)
        # if TAPEDECKDEBUG is in the environment we dump out the raw pickles so
        # we can use "python3 -m pickletools <file>" to dump out the actual
        # raw pickle content and determine why there was a mismatch; to be used
        # when playback raises RecordedCallNotFoundError
        if "TAPEDECKDEBUG" in os.environ and context:
            calldir = Path(str(self.deck) + "-calls")
            calldir.mkdir(exist_ok=True)
            our_meta = context.meta[self.LABEL_TAPE]
            channel = our_meta[self.LABEL_CHANNEL]
            ordinal = our_meta[self.LABEL_ORDINAL]
            fname = f"{('record' if self.mode == Mode.Recording else 'playback')}-{channel}-{ordinal}.pickle"
            with (calldir / fname).open("wb") as fp:
                fp.write(raw)
        uniq = sha256(raw)
        result = uniq.hexdigest()
        return result

    def _log(self, level: int, category: str, action: str, msg: str) -> None:
        """
        Common funnel for logs.
        """
        msg = f"TAPE: {category}({action}): {msg}"
        self._logger.log(level, msg)

    def _log_ex(self, action: str, context: CallContext, ex: Exception) -> None:
        """
        Logs recording and playback events for exceptions.

        Avoids building the log message string if the message would not be logged.
        """
        if self._logger.isEnabledFor(logging.DEBUG):
            self._log(
                logging.DEBUG,
                action,
                "exception",
                f"{context}: {type(ex).__name__}: {ex}",
            )

    def _log_result(self, action: str, context: CallContext, result: Any) -> None:
        """
        Logs recording and playback events for results.

        Avoids building the log message string if the message would not be logged.
        """
        if self._logger.isEnabledFor(self.DEBUG_WITH_RESULTS):
            context.meta[self.LABEL_TAPE][self.LABEL_RESULT] = result
        if self._logger.isEnabledFor(logging.DEBUG):
            self._log(
                logging.DEBUG,
                action,
                "result",
                str(context),
            )
        if self._logger.isEnabledFor(self.DEBUG_WITH_RESULTS):
            context.meta[self.LABEL_TAPE].pop(self.LABEL_RESULT)

    def _redact(self, entity: Any, return_bytes: bool = False) -> Any:
        """
        Redacts any known secrets in an object by converting it to pickled
        binary form, then doing a binary secret replacement, then unpickling.

        This is used before we hash contexts and before we store results to
        make sure there are no secrets in the recording.  The secrets must
        be fed to us from the consumer (self.redactions).

        Raises:
            PicklingError if something in the context cannot be pickled.
        """
        raw = pickle.dumps(entity, protocol=self.PICKLE_PROTOCOL)
        for secret in self.redactions:
            binary_secret = secret.encode()
            redacted_secret = ("^" * len(secret)).encode()
            raw = raw.replace(binary_secret, redacted_secret)
        return pickle.loads(raw) if not return_bytes else raw  # nosec

    def _reduce_call(self, context: CallContext) -> Callable:
        """
        Normally we try to store the call verbatim but if pickling fails
        we fall back to a string representation.

        Returns:
            The original call so it can be replaced after recording
            using a fianlly block.
        """
        sig = repr(context.call)
        pos = 0
        while True:
            pos = sig.find(" at 0x", pos)
            if pos == -1:
                break
            pos += 6
            end = pos
            while sig[end].isalnum():
                end += 1
            sig = sig[:pos] + "0decafcoffee" + sig[end:]
            pos += 12
        result = context.call
        context.call = sig
        return result
