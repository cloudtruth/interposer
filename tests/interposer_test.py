# -*- coding: utf-8 -*-
#
# Copyright (C) 2019 Tuono, Inc.
# All Rights Reserved
#
import logging
import shutil
import tempfile
import unittest

from pathlib import Path

from interposer import Interposer
from interposer import Mode
from interposer import PlaybackError
from interposer import ScopedInterposer


# for testing a standalone method
rv = True


def standalone_method():
    return rv


class MyVerySpecificError(RuntimeError):
    pass


class SomeClass(object):

    throw_exception = True

    def __init__(self, result: object):
        """
        Store a result for say_hi.  If this derives from Exception then
        it will raise when called.
        """
        self.result = result

    def say_hi(self, greeting: str = "hello") -> str:
        """
        Returns the result stored in the initializer.
        Raises an error if we're in playback mode, since we shouldn't be called.
        """
        if isinstance(self.result, Exception):
            raise self.result
        return "hello " + str(self.result)

    def give_up(self):
        if self.throw_exception:
            raise MyVerySpecificError("ouchies")


class InterposerTest(unittest.TestCase):

    logging.basicConfig(level=logging.DEBUG)

    def setUp(self):
        self.datadir = Path(tempfile.mkdtemp())
        SomeClass.throw_exception = True

    def tearDown(self):
        shutil.rmtree(str(self.datadir))

    def test_good_function_wrapping(self):
        """
        This proves the recording and playback are working properly for a
        bare function.  standalone_method returns the global rv if it is
        not being played back...
        """
        global rv
        with ScopedInterposer(self.datadir / "recording", Mode.Recording) as uut:
            wm = uut.wrap(standalone_method)
            rv = True
            self.assertEqual(wm(), True)
            rv = False
            self.assertEqual(wm(), False)

        with ScopedInterposer(self.datadir / "recording", Mode.Playback) as uut:
            wm = uut.wrap(standalone_method)
            # rv is still False, but since we're playing back...
            self.assertEqual(wm(), True)
            self.assertEqual(wm(), False)

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
            SomeClass.throw_exception = False
            self.assertIsNone(wt.give_up())

        with ScopedInterposer(self.datadir / "recording", Mode.Playback) as uut:
            # if actually called, say_hi should return False
            t = SomeClass(False)
            wt = uut.wrap(t)
            self.assertIn("say_hi", dir(wt))
            # but we are playing back so it returns what was recorded
            self.assertEqual(wt.say_hi(), "hello True")
            # SomeClass is currently set not to throw, but we're playing back
            # so we replay the exception
            with self.assertRaises(MyVerySpecificError) as re:
                wt.give_up()

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

        pb1 = Interposer(self.datadir / "recording", Mode.Playback)
        pb1.open()
        pb1.open()  # idempotent
        t1 = SomeClass(None)
        wt1 = pb1.wrap(t1, channel="nsone")
        pb2 = Interposer(self.datadir / "recording", Mode.Playback)
        pb2.open()
        t2 = SomeClass(None)
        wt2 = pb2.wrap(t2, channel="nstwo")
        self.assertEqual(wt1.say_hi(), "hello one:one")  # 1st call in channel nsone
        self.assertEqual(wt2.say_hi(), "hello second:one")  # 1st call in channel nstwo
        self.assertEqual(wt1.say_hi(), "hello one:two")  # 2nd call in channel nsone
        pb2.close()
        pb2.close()  # idempotent
        pb1.close()

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