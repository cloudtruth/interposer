# -*- coding: utf-8 -*-
#
# Copyright (C) 2019 - 2020 Tuono, Inc.
# All Rights Reserved
#
import json
import logging
import shelve
import types

from contextlib import AbstractContextManager
from enum import auto
from enum import Enum
from hashlib import sha1
from pathlib import Path

from wrapt import ObjectProxy


class Mode(Enum):
    """
    The running mode of the interposer.
    """

    Playback = auto()
    Recording = auto()


class PlaybackError(KeyError):
    """
    The interposer never recorded a method call with the parameters given,
    or the sequence of calls somehow changed between recording and playback.

    The recording needs to be regenerated due to code changes.
    """

    pass


class Interposer(object):
    """
    TODO: turn this into a README and make it usable...
          right now it's between half and mostly right...

    Record any function calls and plays back the result.

    The recorder is useful where you are dealing with a third party
    library and you would like to:

      - Occasionally ensure your code works live,
      - Record detailed responses from third party libraries instead
        of mocking them,
      - Always ensure your code works.

    Recording has advantages and disadvantages, so the right solution
    for your situation depends on many things.  Recording eliminates
    the need to produce and maintain mocks.  Mocks of third party
    libraries that change or are not well understood are fragile and
    lead to a false sense of safety.  Recordings on the other hand
    are always correct, but they need to be regenerated when your
    logic changes around the third party calls.

    Important:
      - This is a resource, so you need to call open() and close() or
        use the ScopedInterposer context manager.

    Usage:
      1. Instantiate an Interposer with a datafile path, and set
         the mode to Recording.
      2. To wrap something, call wrap() and pass in the definition.
      3. Use the returned wrapper as if it were the actual definition
         that was wrapped.
      4. Every use of the wrapped definition will record:
         - The call name
         - The parameters (positional and keyword)
         - The return value, if no exception was raised
         - The exception raised, should one be raised

    Restrictions:
      - Return values and Exceptions must be safe for pickling.  Some
        third party APIs use local definitions for exceptions, for example,
        and local definitions cannot be pickled.  If you get a pickling
        error, you should subclass Interposer and provide your own
        cleanup routine(s) as needed to substitute a class that can be
        substituted for the local definition.

    Advanced Usage:
      - FIXME
      - During playback, the method call and parameters are matched
        up against previously recorded calls, and either a value is
        returned or an exception is raised.
      - If you have sensitive information you do not want recorded,
        subclass Interposer and provide your own cleanup routines
        to make the data safe.
      - You can set the environment variable RECORDING_CONTEXT to
        modify the recording and playback; if present this string
        will be added to disambiguate recordings in the same datafile.

    Recording file format history:
      -  1: code did not record exceptions
      -  2: added exception recording and playback support
      -  3: renamed "context" to "channel" maintaining compatibility with v2 recordings
      -  4: ordinal counting of calls for linear playback?  (@healem) ?

    Attributes:
        tape:  The shelve instance that stores the recordings

    Methods:
        record:   Record a method call to a venue-specific API (like boto3)
        playback: Playback the result of a previous recording

    Gotchas / TODOs:
      - Do not have two recorders active on the same datafile.
      - Identical method names and parameter lists in different classes
        are treated as equals.  Use the "channel" to differentiate them.
        For example if you have a sequence of recordings that are played
        back and they have some overlap, give each one a unique channel.
        Channel is assigned when something is wrapped.
    """

    VERSION = 4

    def __init__(self, datafile: Path, mode: Mode, encoder=None):
        """
        Initializer.

        Attributes:
          datafile (Path): The full path to the recording filename.
          mode (Mode): The operational mode - Playback or Recording.
          encoder: used by json.dumps as the "cls" argument to encode more
                   than just standard data types
        """
        self.call_order = {}
        self.playback_call_order = {}
        self.deck = datafile
        self.encoder = encoder
        self.logger = logging.getLogger(__name__)
        self.mode = mode
        self.playback_index = {}
        self.tape = None
        self.version = self.VERSION
        self.in_simulation = False

        self.logger.debug(
            f"TAPE: Initialized Interposer (v{self.VERSION}) with datafile={datafile}"
        )

    def open(self):
        if not self.tape:
            if self.mode == Mode.Playback:
                # Open db file read-only
                self.tape = shelve.open(str(self.deck), flag="r", protocol=4)
                self.version = self.tape.get("_version", 1)
                self.logger.debug(
                    f"TAPE: Opened {self.deck} for playback using version {self.version}"
                )
                # Load the call order if present
                if "deck_call_order" in self.tape:
                    self.call_order = self.tape["deck_call_order"]
            else:
                # Open db file rw, and create if it doesn't exist
                self.tape = shelve.open(str(self.deck), flag="c", protocol=4)
                self.tape["_version"] = self.VERSION

            self.logger.debug(
                f"TAPE: Opened {self.deck} for {self.mode} using version {self.version}"
            )

    def close(self):
        if self.tape:
            if self.mode != Mode.Playback:
                self.tape["deck_call_order"] = self.call_order
            self.tape.close()
            self.tape = None

    def wrap(self, thing, channel="default", as_method=False):
        """
        Wrap a class or a method for recording or playback.

        The information is stored as part of a channel in the recording file.
        This is useful to separate recordings so they do not experience crosstalk.

        Arguments:
          thing: the thing to wrap (a class or a method)
          channel: the channel name.  If no channel is specified, everything is
                   placed into a channel named "default"
          as_method: record an initializer of a class with arguments where said
                     class only provides properties and no methods

          TODO: the presence of as_method means we're not properly capturing
                the class initializer; I would consider this a HACK that needs
                more thought.  Essentially any class we wrap, we're ignoring the
                arguments as part of a signature; we're only recording method calls
                and using only arguments on the method calls to disambiguate.
        """
        if as_method or isinstance(thing, (types.FunctionType, types.MethodType)):
            return _InterposerMethodWrapper(self, thing, channel=channel)
        else:
            return _InterposerClassWrapper(self, thing, channel=channel)

    def cleanup_exception_pre(self, ex):
        """
        When an exception is going to be recorded, this intercept allows the
        exception to be changed.  This is necessary for any exception that
        cannot be pickled.

        Common ways to deal with pickling errors here are:
          - Set one of the properties to None
          - Return a doppleganger class (looks like, smells like, but does not
            derive from the original).
        """
        return ex

    def cleanup_exception_post(self, ex):
        """
        Modify an exception during playback before it is thrown.
        """
        return ex

    def cleanup_parameters_pre(self, params):
        """
        Allows the data in the parameters (this uniquely identifies a request)
        to be modified.  This is useful in wiping out any credentials or other
        sensitive information.  When replaying in tests, if you set these bits
        to the same value, the recorded playback will match.
        """
        return params

    def cleanup_parameters_post(self, params):
        """
        Modify parameters during playback before they are hashed to locate
        a recording.
        """
        return params

    def cleanup_result_pre(self, params, result):
        """
        Some return values cannot be pickled.  This interceptor allows you to
        rewrite the result so that it can be.  Sometimes this means removing
        a property (setting it to None), sometimes it means replacing the
        result with something else entirely (a doppleganger with the same
        methods and properties as the original, but isn't derived from it).

        Common ways to deal with pickling errors here are:
          - Set one of the properties to None
          - Return a doppleganger class (looks like, smells like, but does not
            derive from the original).
        """
        return result

    def cleanup_result_post(self, result):
        """
        Modify the return value during playback before it is returned.
        """
        return result

    def clear_for_execution(self, params):
        """
        Called before any method is actually executed.  This can be used to
        implement a mechanism that ensures only certain methods are called.

        Implementations are free to raise whatever error they would like to
        identify this situation.
        """
        pass

    def _record(self, params: dict, result: object, exception: object = None):
        """
        Records the parameters and result of an API call.

        To get the result of this recording at a later time, call playback:
            _playback(params)

        The result for each param signature are stored in a list, in the order the result is
        recorded.  Playback will replay the result in the same order as the original recording.

        Args:
            params:  A dict containing: { method: <method called>, args: [args], kwargs: {kwargs} }
            result: The result from the API call, as any python object that can be pickled
            exception: The exception that occurred as a result of the API call, if any
        """
        # Use json.dumps to turn whatever parameters we have into a string, so we can hash it
        prefix = sha1(  # nosec
            json.dumps(params, sort_keys=True, cls=self.encoder).encode()
        ).hexdigest()
        result_key = f"{prefix}.results"

        result_list = self.tape.get(result_key, [])
        result_list.append((result, exception))

        # record the call in the call_order list
        if params["channel"] in self.call_order:
            self.call_order[params["channel"]]["calls"].append(params)
        else:
            self.call_order[params["channel"]] = {}
            self.call_order[params["channel"]]["calls"] = [params]

        if exception is None:
            self.logger.debug(
                f"TAPE: Recording RESULT {result_key} call #{(len(result_list) - 1)} "
                f"for params {params} "
                f"type={(result.__class__.__name__ if result is not None else 'None')}"
            )
        else:
            self.logger.debug(
                f"TAPE: Recording EXCEPTION {result_key} call #{(len(result_list) - 1)} "
                f"for params {params} type={(exception.__class__.__name__)}"
            )
        self.tape[result_key] = result_list

    def _playback(self, params: dict) -> object:
        """playback a previous recording

        Args:
            params:  A dict containing: { method: <method called>, args: [args], kwargs: {kwargs} }

        Returns:
            Whatever object was stored
        """
        new_params = self.cleanup_parameters_post(params)
        prefix = sha1(  # nosec
            json.dumps(new_params, sort_keys=True, cls=self.encoder).encode()
        ).hexdigest()
        result_key = f"{prefix}.results"

        # Check the call order and issue a warning if warranted
        if self.call_order:
            channel = new_params.get("channel")
            if channel:
                index = self.call_order[channel].get("call_index", 0)
                calls = self.call_order[channel]["calls"]
                if len(calls) <= index:
                    raise PlaybackError("Not enough calls recorded to satisfy.")
                if new_params != calls[index]:
                    msg = f"Call {new_params} played back as call in a different order than recorded. "
                    msg += f"Call at index {index}: {self.call_order[channel]['calls'][index]}"
                    raise PlaybackError(msg)

                self.call_order[channel]["call_index"] = index + 1

            # record the call in the playback_call_order list
            if new_params["channel"] in self.playback_call_order:
                self.playback_call_order[new_params["channel"]]["calls"].append(
                    new_params
                )
            else:
                self.playback_call_order[new_params["channel"]] = {}
                self.playback_call_order[new_params["channel"]]["calls"] = [new_params]

        located = self.tape.get(result_key)
        if not located:
            raise PlaybackError(f"No calls for params {new_params} were ever recorded.")
        index = self.playback_index.get(result_key, 0)
        if len(located) <= index:
            raise PlaybackError(
                f"Call #{index} for params {new_params} was never recorded."
            )
        recorded = located[index]
        self.playback_index[result_key] = index + 1

        if self.version == 1:
            result = recorded
            exception = None
        else:
            result = recorded[0]
            exception = recorded[1]

        if exception is None:
            self.logger.debug(
                f"TAPE: Playing back RESULT for {result_key} call #{index} "
                f"for params {new_params} "
                f"type={(result.__class__.__name__ if result is not None else 'None')}"
            )
            return self.cleanup_result_post(result)
        else:
            self.logger.debug(
                f"TAPE: Playing back EXCEPTION for {result_key} call #{index} "
                f"for params {new_params} type={(exception.__class__.__name__)}"
            )
            raise self.cleanup_exception_post(exception)


class ScopedInterposer(Interposer, AbstractContextManager):
    """
    Allows the interposer to be used properly as a resource, since it
    handles a file.
    """

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()


class _InterposerClassWrapper(ObjectProxy):
    """
    Use Interposer.wrap() to wrap something for recording or playback.

    This class is an implementation detail of Interposer.

    This class wraps a class, ensuring that every method called on the wrapped
    class gets transparently proxied by the _InterposerMethodWrapper allowing
    that method call to be optionally recorded.  It will also wrap anyxi
    attributes of the target class with this class, so that any methods on
    those embedded objects will also be wrapped.
    """

    def __init__(self, recorder: Interposer, clazz, channel="default"):
        super().__init__(clazz)
        self._self_channel = channel
        self._self_recorder = recorder

    def __call__(self, *args, **kwargs):
        return self.__wrapped__(*args, **kwargs)

    def __getattr__(self, name):
        attr = super().__getattr__(name)
        if isinstance(attr, (types.FunctionType, types.MethodType)):
            # Wrap the methods that get called
            # self.recorder.logger.debug(f"TAPE: wrapping method {name}")
            attr = _InterposerMethodWrapper(
                self._self_recorder, attr, channel=self._self_channel
            )
        elif name == "__wrapped__":
            # Prevent infinite loops
            pass
        else:
            # In the case of Azure, the methods are on sub-objects under the client object
            # So we need to iterate down until we get to the method
            # self.recorder.logger.debug(f"TAPE: wrapping attr {name}")
            attr = _InterposerClassWrapper(
                self._self_recorder, attr, channel=self._self_channel
            )
        return attr


class _InterposerMethodWrapper(ObjectProxy):
    """
    This class wraps a method and optionally can record all parameters
    and the result to the Interposer.
    """

    def __init__(self, recorder: Interposer, method, channel="default"):
        super().__init__(method)
        self._self_channel = channel
        self._self_recorder = recorder

    def __call__(self, *args, **kwargs):
        params = {"method": self.__wrapped__.__name__, "args": args, "kwargs": kwargs}
        params[
            "channel" if self._self_recorder.version >= 3 else "context"
        ] = self._self_channel
        if self._self_recorder.mode == Mode.Playback:
            self._self_recorder.clear_for_execution(params)
            return self._self_recorder._playback(params)
        else:
            try:
                self._self_recorder.clear_for_execution(params)
                result = self._self_recorder.cleanup_result_pre(
                    params, self.__wrapped__(*args, **kwargs)
                )
                params = self._self_recorder.cleanup_parameters_pre(params)

                self._self_recorder._record(params, result)
                return result
            except Exception as ex:
                params = self._self_recorder.cleanup_parameters_pre(params)
                ex = self._self_recorder.cleanup_exception_pre(ex)
                self._self_recorder._record(params, None, exception=ex)
                raise ex
