# -*- coding: utf-8 -*-
#
# Copyright (C) 2019 - 2020 Tuono, Inc.
# All Rights Reserved
#
import logging
import shutil
import tempfile
import time
import types
import unittest
import uuid

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict
from typing import Generator

from interposer import Interposer
from interposer import Mode
from interposer import PlaybackError
from interposer import ResultHandlingFlag
from interposer import ScopedInterposer
from interposer.interposer import _InterposerWrapper


# for testing a standalone method
rv = True


def standalone_function():
    return rv


def builtin_function() -> int:
    return datetime.now().timestamp()


class MyEnum(Enum):
    FOO = 1


class MyVerySpecificError(RuntimeError):
    pass


def numberGenerator(n):
    if n < 20:
        number = 0
        while number < n:
            yield number
            number += 1
    else:
        return


class SomeClass(object):
    def __init__(self, result: object, secret: str = None):
        """
        Store a result for say_hi.  If this derives from Exception then
        it will raise when called.
        """
        self.result = result
        self.auth = {"secret": secret}

        self.throw_exception = True
        self.throw_if_range_called = False

    def say_hi(self, greeting: str = "hello", second: object = None) -> str:
        """
        Returns the result stored in the initializer.
        Raises an error if we're in playback mode, since we shouldn't be called.

        second is used to ensure we can encode some types natively like datetime
        """
        if isinstance(self.result, Exception):
            raise self.result
        return f"{greeting} {self.result}" + ("" if not second else " " + str(second))

    def give_up(self):
        if self.throw_exception:
            raise MyVerySpecificError("ouchies")

    def generated_numbers(self, n: int) -> Generator[int, None, None]:
        """
        Returns a generator.  These are harder to deal with
        because they only generate their contents once, so we
        have to extract the contents before we record and return.
        """
        if self.throw_if_range_called:
            raise NotImplementedError("should have satisfied result from recording!")
        return numberGenerator(5)

    @property
    def get_complex_stuff(self):
        """
        In this case the return value is a class so that has to be wrapped.
        """
        return SomeClass(self.result)


class SomeClassSecretRemoverInterposer(Interposer):
    """
    Eliminates the secret from being in the recording.

    This is done two ways:

    1. By removing it from the params used to hash a unique call.
    2. By removing it from any result.
    """

    def cleanup_parameters_pre(self, params: Dict) -> Dict:
        """
        Remove the secret from the parameters used to initialize it
        in the recording.
        """
        if "secret" in params["kwargs"]:
            result = deepcopy(params)
            result["kwargs"]["secret"] = "REDACTED_SECRET"  # nosec
            return super().cleanup_parameters_pre(result)
        else:
            return params

    @contextmanager
    def cleanup_result_pre(
        self, params: Dict, result: object, flags: ResultHandlingFlag
    ) -> None:
        """
        Remove the secret from the initialized class in the recording.
        """
        if "secret" in params["kwargs"]:
            original_secret = result.__dict__["auth"]["secret"]
            result.__dict__["auth"]["secret"] = "REDACTED_SECRET"  # nosec
            # this is good form in case there are stacked interposers
            with super().cleanup_result_pre(params, result, flags=flags) as (
                scrubbed_result,
                flags,
            ):
                yield scrubbed_result, flags
            result.__dict__["auth"]["secret"] = original_secret
        else:
            yield result, flags


class SomeClassGeneratorInterposer(Interposer):
    """
    Tests handling generators by overwriting the original result.
    """

    @contextmanager
    def cleanup_result_pre(
        self, params: Dict, result: object, flags: ResultHandlingFlag
    ) -> None:
        if params["method"] == "generated_numbers":
            assert isinstance(result, types.GeneratorType)
            new_result = list(result)
            flags |= ResultHandlingFlag.REPLACE
            # this is good form in case there are stacked interposers
            with super().cleanup_result_pre(params, new_result, flags=flags) as (
                scrubbed_result,
                flags,
            ):
                yield scrubbed_result, flags


class SomeClassRecordNothingInterposer(Interposer):
    """
    Not very practical but here we simply state that no recording should be done.
    """

    @contextmanager
    def cleanup_result_pre(
        self, params: Dict, result: object, flags: ResultHandlingFlag
    ) -> None:
        flags ^= ResultHandlingFlag.RECORD
        # this is good form in case there are stacked interposers
        with super().cleanup_result_pre(params, result, flags=flags) as (
            scrubbed_result,
            flags,
        ):
            yield scrubbed_result, flags


class InterposerTest(unittest.TestCase):

    logging.basicConfig(level=logging.DEBUG)

    def setUp(self):
        self.datadir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(str(self.datadir))

    def test_function_wrapping(self):
        """
        This proves the recording and playback are working properly for a
        bare function.  standalone_function returns the global rv if it is
        not being played back...
        """
        global rv
        with ScopedInterposer(self.datadir / "recording", Mode.Recording) as uut:
            wm = uut.wrap(standalone_function)
            rv = True
            self.assertEqual(wm(), True)
            rv = False
            self.assertEqual(wm(), False)

        with ScopedInterposer(self.datadir / "recording", Mode.Playback) as uut:
            wm = uut.wrap(standalone_function)
            # rv is still False, but since we're playing back...
            self.assertEqual(wm(), True)
            self.assertEqual(wm(), False)

    def test_builtin_functions(self):
        """
        Proves builtin functions like datetime.now are captured.  They
        are different "types" than a standard function.
        """
        stamp = None

        with ScopedInterposer(self.datadir / "recording", Mode.Recording) as uut:
            wm = uut.wrap(builtin_function)
            stamp = wm()

        time.sleep(0.1)

        with ScopedInterposer(self.datadir / "recording", Mode.Playback) as uut:
            wm = uut.wrap(builtin_function)
            chk = wm()
            assert chk == stamp  # no time passed when playing back recording

    def test_ok_additional_types(self):
        """
        Use datetime and enum in arguments and it is okay, we convert to
        a form that can be json encoded.
        """
        t = datetime.now()
        with ScopedInterposer(self.datadir / "recording", Mode.Recording) as uut:
            # if actually called, say_hi should return True
            wt = uut.wrap(SomeClass(True))
            assert wt.say_hi(second=t) == f"hello True {str(t)}"
            assert wt.say_hi(second=MyEnum.FOO) == "hello True MyEnum.FOO"

        with ScopedInterposer(self.datadir / "recording", Mode.Playback) as uut:
            wt = uut.wrap(SomeClass(False))
            assert wt.say_hi(second=t) == f"hello True {str(t)}"
            assert wt.say_hi(second=MyEnum.FOO) == "hello True MyEnum.FOO"
            with self.assertRaises(PlaybackError):
                wt.say_hi(second="foobar")  # never called during recording
            wt.throw_if_range_called = True

    def test_generators(self):
        """
        Tests how we handle generators.
        """
        uut = SomeClassGeneratorInterposer(self.datadir / "recording", Mode.Recording)
        uut.open()
        wt = uut.wrap(SomeClass(True))
        # although it would normally return a generator, in order to record
        # it we drain the generator to a list, record it, and return the list
        # based on how SomeClassGeneratorInterposer is configured
        assert wt.generated_numbers(5) == [0, 1, 2, 3, 4]
        uut.close()

        with ScopedInterposer(self.datadir / "recording", Mode.Playback) as uut:
            wt = uut.wrap(SomeClass(False))
            wt.throw_if_range_called = True
            # if the method is actually called it will now throw
            # instead we prove it is satisfying the result from the recording
            assert wt.generated_numbers(5) == [0, 1, 2, 3, 4]

    def test_wrappable(self):
        """
        Test the logic that determines what is wrappable.
        """
        with ScopedInterposer(self.datadir / "recording", Mode.Recording) as uut:
            # modules
            assert isinstance(logging, types.ModuleType)
            assert uut.wrappable(logging)
            # class definitions
            assert isinstance(Path, type)
            assert uut.wrappable(Path)
            # class instances
            assert isinstance(self.datadir, object)
            assert uut.wrappable(self.datadir)
            # bare functions
            assert isinstance(standalone_function, types.FunctionType)
            assert uut.wrappable(standalone_function)
            # builtin functions
            assert isinstance(datetime.now, types.BuiltinFunctionType)
            assert uut.wrappable(datetime.now)

            # instantiating a wrapped class definition returns a wrapped instance
            assert isinstance(uut.wrap(Path()), _InterposerWrapper)

            # primitives
            assert not uut.wrappable(None)
            assert not uut.wrappable(True)
            assert not uut.wrappable(42)
            assert not uut.wrappable(42.0)
            assert not uut.wrappable(complex(42))
            assert not uut.wrappable(list())
            assert not uut.wrappable(tuple())
            assert not uut.wrappable(set())
            assert not uut.wrappable(dict())
            assert not uut.wrappable(bytearray(1))

    def test_good_class_wrapping(self):
        """
        This proves the recording and playback are working properly for class
        methods.

        Note that the configuration of the class and class variables are not
        taken into account when hashing the class method call.  This is a known
        limitation of the current implementation.

        During recording the actual code (say_hi) is executed and returns
        an expected result.  Then the value of the expected result is changed
        and the mode is changed to playback.  The code proves that in playback
        mode, say_hi is never actually called.  Instead the previously
        recorded call is played back.
        """
        with ScopedInterposer(self.datadir / "recording", Mode.Recording) as uut:
            # if actually called, say_hi should return True
            t = SomeClass(True)
            wt = uut.wrap(t)
            self.assertIn("say_hi", dir(wt))
            # prove it does
            self.assertEqual(wt.say_hi(), "hello True")
            # prove we handle exceptions
            with self.assertRaises(MyVerySpecificError) as re:
                wt.give_up()
            self.assertRegex("ouchies", str(re.exception))
            wt.throw_exception = False
            self.assertIsNone(wt.give_up())

        with ScopedInterposer(self.datadir / "recording", Mode.Playback) as uut:
            # if actually called, say_hi should return False
            t = SomeClass(False)
            wt = uut.wrap(t)
            self.assertIn("say_hi", dir(wt))
            # but we are playing back so it returns what was recorded
            self.assertEqual(wt.say_hi(), "hello True")
            # prove we replay exceptions
            wt.throw_exception = False  # but the original call threw
            with self.assertRaises(MyVerySpecificError):
                wt.give_up()
            wt.throw_exception = True  # but the original call did not
            self.assertIsNone(wt.give_up())

    def test_property_handling(self):
        """
        This proves recording and playback are working property for class properties.
        In this case we have a class property that returns a new class initialized with
        the same value, however during playback we see the recording is replayed, otherwise
        it would have said "hello False".
        """
        with ScopedInterposer(self.datadir / "recording", Mode.Recording) as uut:
            # if actually called, say_hi should return True
            t = SomeClass(True)
            wt = uut.wrap(t)
            assert wt.get_complex_stuff.say_hi() == "hello True"

        with ScopedInterposer(self.datadir / "recording", Mode.Playback) as uut:
            t = SomeClass(False)
            wt = uut.wrap(t)
            assert wt.get_complex_stuff.say_hi() == "hello True"

    def test_multiple_channels_multiple_results(self):
        """ Prove the same wrapped entity can be disambiguated with channels. """
        with ScopedInterposer(self.datadir / "recording", Mode.Recording) as uut:
            t = SomeClass("one:one")
            z = SomeClass("second:one")
            wt = uut.wrap(t, channel="nsone")
            zt = uut.wrap(z, channel="nstwo")
            self.assertEqual(wt.say_hi(), "hello one:one")
            self.assertEqual(zt.say_hi(), "hello second:one")
            t.result = "one:two"
            self.assertEqual(wt.say_hi(), "hello one:two")

        pb = Interposer(self.datadir / "recording", Mode.Playback)
        pb.open()
        pb.open()  # idempotent
        t1 = SomeClass(None)
        wt1 = pb.wrap(t1, channel="nsone")
        t2 = SomeClass(None)
        wt2 = pb.wrap(t2, channel="nstwo")
        self.assertEqual(wt1.say_hi(), "hello one:one")  # 1st call in channel nsone
        self.assertEqual(wt2.say_hi(), "hello second:one")  # 1st call in channel nstwo
        self.assertEqual(wt1.say_hi(), "hello one:two")  # 2nd call in channel nsone
        pb.close()
        pb.close()  # idempotent

    def test_playback_out_of_order(self):
        """
        Prove we warn when playback is not in the same order as recording.

        This means we found a result but it was not in the recorded sequence.
        The recording probably needs to be regenerated.
        """
        with ScopedInterposer(self.datadir / "recording", Mode.Recording) as uut:
            # if actually called, say_hi should return True
            t = SomeClass(True)
            wt = uut.wrap(t)
            self.assertIn("say_hi", dir(wt))
            # yes, it does
            self.assertEqual(wt.say_hi(), "hello True")
            with self.assertRaises(MyVerySpecificError):
                wt.give_up()

        with ScopedInterposer(self.datadir / "recording", Mode.Playback) as uut:
            # if actually called, say_hi should return False
            t = SomeClass(False)
            wt = uut.wrap(t)
            self.assertIn("say_hi", dir(wt))
            with self.assertRaises(PlaybackError):
                # when we recorded, say_hi was called first, but now it is not
                wt.give_up()

    def test_playback_cannot_replay(self):
        """
        If we cannot find a hash for the params given to a method we raise an error.

        This means we never recorded the method called this way.
        The recording needs to be regenerated.
        """
        with ScopedInterposer(self.datadir / "recording", Mode.Recording) as uut:
            # if actually called, say_hi should return True
            t = SomeClass(True)
            wt = uut.wrap(t)
            self.assertIn("say_hi", dir(wt))
            # yes, it does
            self.assertEqual(wt.say_hi(), "hello True")

        with ScopedInterposer(self.datadir / "recording", Mode.Playback) as uut:
            # if actually called, say_hi should return False
            t = SomeClass(False)
            wt = uut.wrap(t)
            with self.assertRaises(PlaybackError):
                # never called with these params
                wt.say_hi(greeting="hola")
            wt.say_hi()
            with self.assertRaises(PlaybackError):
                # was never called a second time
                wt.say_hi()

    def test_result_flags_disable_recording(self):
        """
        Tests that recording flags can stop recording.

        Not intended to be an example, just to exercise the record flag turned off.
        """
        uut = SomeClassRecordNothingInterposer(
            self.datadir / "recording", Mode.Recording
        )
        uut.open()
        wt = uut.wrap(SomeClass)
        wt(True)
        uut.close()

        with ScopedInterposer(self.datadir / "recording", Mode.Playback) as uut:
            wt = uut.wrap(SomeClass)
            with self.assertRaises(PlaybackError):
                wt(True)

    def test_recording_contains_no_secret(self):
        """
        Check that if we properly implement cleanup_parameters_pre, any secret
        in the parameters is not recorded at all.  When we wrap a class definition
        we end up storing the parameters passed to it, which may include a secret,
        so a custom interposer can remove that secret from the recording.
        """
        uut = SomeClassSecretRemoverInterposer(
            self.datadir / "recording", Mode.Recording
        )
        uut.open()
        secret = str(uuid.uuid4())
        # wrap the class definition so that we record the __init__ behavior
        wt = uut.wrap(SomeClass)
        # by instantiating an object from the wrapped class definition, we
        # end up storing "t" in the database (pickled), and during playback
        # when "t" is instantiated is is provided entirely from the recording.
        t = wt(True, secret=secret)
        self.assertEqual(t.say_hi(), "hello True")
        uut.close()

        with (self.datadir / "recording").open("rb") as fp:
            data = fp.read()
            assert (
                "REDACTED_SECRET".encode() in data  # nosec
            ), "did not find redacted secret in data file"
            assert secret.encode() not in data, "found original secret in data file"

        with ScopedInterposer(self.datadir / "recording", Mode.Playback) as uut2:
            wt = uut2.wrap(SomeClass)
            with self.assertRaises(PlaybackError):
                # due to the current interposer design, we store the argument lists
                # in the database so we have to scrub away the secret in the params
                # which means on playback runs we must provide the redacted version
                # in order to match
                wt(True, secret=secret)
            t = wt(True, secret="REDACTED_SECRET")  # nosec
            assert t.say_hi() == "hello True"
