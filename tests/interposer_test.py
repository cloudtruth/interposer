# -*- coding: utf-8 -*-
#
# Copyright (C) 2019 - 2020 Tuono, Inc.
# All Rights Reserved
#
import datetime
import inspect
import logging

from dataclasses import asdict
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from unittest import TestCase

from interposer import CallBypass
from interposer import CallContext
from interposer import CallHandler
from interposer import Interposer
from interposer import isinterposed


def standalone_function(foo: int):
    return 42


class SimpleError(RuntimeError):
    """ Specific error for SimpleClass to throw. """

    pass


class SimpleClass(object):
    """ A simple class. """

    def __init__(self, *args, **kwargs):
        self.jade = "SPEICLA"
        pass

    def regular_call(self, arg1, arg2, kwarg1=None, kwarg2=None):
        if arg2 != 42:
            raise SimpleError("arg2 must be 42")
        return kwarg1

    @property
    def guide(self) -> str:
        return "DON'T PANIC!"


class AdventureError(RuntimeError):
    """ Used to prove a bypass exception can be raised. """

    pass


class AdventureCallHandler(CallHandler):
    """
    On a method call, bypasses the return value or raises to demonstrate
    how an interposer can prevent an actual call from happening.
    """

    def on_call_begin(self, context: CallContext) -> Optional[CallBypass]:
        if inspect.ismethod(context.call):
            if len(context.args) > 1 and context.args[1] != 42:
                raise AdventureError("PLUGH")
            return CallBypass(result="XYZZY")


class AuditingCallHandler(CallHandler):
    """
    Implements a very simple call audit mechanism for testing.
    """

    def __init__(self):
        super().__init__()
        self.calls: List[Dict] = []
        self.ordinal: int = -1

    def on_call_begin(self, context: CallContext) -> Optional[CallBypass]:
        """ If we return nothing, the call happens. """
        assert not isinterposed(context.call)

        name = getattr(context.call, "__qualname__", getattr(context.call, "__name__"))

        self.calls.append(
            {
                "name": name,
                "args": context.args,
                "kwargs": context.kwargs,
                "type": type(context.call),
            }
        )
        self.ordinal += 1
        assert len(self.calls) == self.ordinal + 1

    def on_call_end_exception(self, context: CallContext, ex: Exception) -> None:
        """ If we do not raise, the original exception gets re-raised. """
        self.calls[self.ordinal]["exception"] = ex

    def on_call_end_result(self, context: CallContext, result: Any) -> Any:
        """ Whatever we return is what gets returned to the original caller. """
        self.calls[self.ordinal]["result"] = result
        return result


class LoggingCallHandler(CallHandler):
    """
    Logs a JSON representation of every call as a debug message and of any
    exception as a log error.
    """

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)

    def on_call_begin(self, context: CallContext) -> Optional[CallBypass]:
        self.logger.debug(str(asdict(context)))

    def on_call_end_exception(self, context: CallContext, ex: Exception) -> None:
        self.logger.error("on_call_end_exception", exc_info=True)  # str(ex))


class InterposerTest(TestCase):
    """
    Tests the basic functionality of the interposer harness.

    This tests wrapping and using a module, class, object, and method.
    It also tests stacking interposers.
    """

    def test_interposer_simple(self):
        """
        I can wrap anything!

        Typical usage is to wrap a third party class or object, but you
        can wrap a module as well.  datetime is our proxy for a third party
        module.

        This test does not prove interposer did anything useful but shows
        you can wrap a variety of things.  Combined with stacked interposer
        implementations you could do all sorts of things like assign calls
        an ordinal number, audit the call, inject request content, etc...
        """
        handler = CallHandler()

        # wrap a module
        uut = Interposer(datetime, handler).datetime(2020, 1, 1, 1, 1, 1)
        assert isinterposed(uut)
        assert isinstance(uut, datetime.datetime)

        # wrap a class
        uut = Interposer(datetime.datetime, handler)(2020, 1, 1, 1, 1, 1)
        assert isinterposed(uut)
        assert isinstance(uut, datetime.datetime)

        # wrap an object
        uut = Interposer(datetime.datetime(2020, 1, 1, 1, 1, 1), handler)
        assert isinterposed(uut)
        assert isinstance(uut, datetime.datetime)

        # wrap a function
        uut = Interposer(standalone_function, handler)(12345)
        assert uut == 42
        # we went through on_call_begin, on_call_end_result but there
        # is no proof in this test, however there is in the others

    def test_interposer_wrapping(self):
        """
        Tests very fundamental behavior of call and getattr using
        around a third-party package.  This demonstrates the expected
        behavior on lookups and calls.
        """
        handler = CallHandler()

        # wrap the datetime module
        # actual type is _Interposer
        # but otherwise looks like the datetime module
        wuut = Interposer(datetime, handler)
        assert isinterposed(wuut)
        assert inspect.ismodule(wuut)
        # autowraps the datetime class from the datetime module
        cuut = wuut.datetime
        assert isinterposed(cuut)
        assert inspect.isclass(cuut)
        # autowraps the static utcnow builtin method in the datetime class
        meth = getattr(cuut, "utcnow")
        assert isinterposed(meth)
        assert inspect.isbuiltin(meth)
        # make a datetime using the utcnow() static method
        # the result is not wrapped since it was not a __call__ on a class
        # so the result is not further captured
        uut = meth()
        assert type(uut) == datetime.datetime
        assert isinstance(uut, datetime.datetime)
        # make a datetime directly
        # the result *is* wrapped since it was a __call__ on a class
        # so anything that it calls is captured
        direct = cuut(2020, 7, 14, 1, 2, 4)
        assert isinterposed(direct)
        assert isinstance(direct, datetime.datetime)

        # exercise the base CallHandler on exception routine for coverage
        with self.assertRaises(TypeError):
            cuut("FOOBAR")

    def test_interposer_subclass(self):
        """
        Uses a simple auditing subclass to prove things out.
        """
        handler = AuditingCallHandler()
        uut = Interposer(SimpleClass, handler)()
        assert uut.regular_call("foo", 42, kwarg1="sam", kwarg2="dean") == "sam"
        with self.assertRaises(SimpleError):
            uut.regular_call("foo", "bar", kwarg1="sam", kwarg2="dean")

        calls = handler.calls
        assert len(calls) == 3

        assert calls[0]["args"] == ()
        assert calls[0]["kwargs"] == {}
        assert calls[0]["name"] == "SimpleClass"
        assert isinstance(calls[0]["result"], SimpleClass)
        assert not isinterposed(calls[0]["result"])
        assert "type" in str(calls[0]["type"])

        assert calls[1]["args"] == ("foo", 42)
        assert calls[1]["kwargs"] == {"kwarg1": "sam", "kwarg2": "dean"}
        assert calls[1]["name"] == "SimpleClass.regular_call"
        assert isinstance(calls[1]["result"], str)
        assert type(calls[1]["result"]) == str
        assert calls[1]["result"] == "sam"
        assert "method" in str(calls[1]["type"])

        assert calls[2]["args"] == ("foo", "bar")
        assert calls[2]["kwargs"] == {"kwarg1": "sam", "kwarg2": "dean"}
        assert calls[2]["name"] == "SimpleClass.regular_call"
        assert isinstance(calls[2]["exception"], SimpleError)
        assert "arg2 must be 42" in str(calls[2]["exception"])
        assert "method" in str(calls[2]["type"])

    def test_interposer_stacking(self):
        """
        Adds two call handlers to gain behavior of both.
        """
        auditor = AuditingCallHandler()
        logger = LoggingCallHandler()
        logger.logger.setLevel(logging.DEBUG)

        with self.assertLogs(logger.logger.name, logging.DEBUG):
            uut = Interposer(SimpleClass, [auditor, logger])()
            assert isinterposed(uut)
        with self.assertLogs(logger.logger.name, logging.ERROR):
            with self.assertRaises(SimpleError):
                uut.regular_call("foo", "bar", kwarg1="sam", kwarg2="dean")

        calls = auditor.calls
        assert len(calls) == 2

        assert calls[0]["args"] == ()
        assert calls[0]["kwargs"] == {}
        assert calls[0]["name"] == "SimpleClass"
        assert isinstance(calls[0]["result"], SimpleClass)
        # the result wrapped after on_call_end_result
        assert not isinterposed(calls[0]["result"])
        assert "type" in str(calls[0]["type"])

        assert calls[1]["args"] == ("foo", "bar")
        assert calls[1]["kwargs"] == {"kwarg1": "sam", "kwarg2": "dean"}
        assert calls[1]["name"] == "SimpleClass.regular_call"
        assert isinstance(calls[1]["exception"], SimpleError)
        assert "arg2 must be 42" in str(calls[1]["exception"])
        assert "method" in str(calls[1]["type"])

    def test_interposer_call_bypass(self):
        """
        Uses a bypassing interposer that always returns "XYZZY" or raises
        AdventureError, but only on method calls.
        """
        uut = Interposer(SimpleClass, AdventureCallHandler())()
        # normally the SimpleClass call would return 42
        # but the interposer is changing the call behavior
        assert uut.regular_call("foo", 42, kwarg1="sam", kwarg2="dean") == "XYZZY"
        with self.assertRaises(AdventureError):
            # normally the SimpleClass would raise SimpleError
            # but the interposer is changing the call behavior
            uut.regular_call("foo", "bar", kwarg1="sam", kwarg2="dean")

    def test_interposer_standalone_function(self):
        """
        Tests how we handle a standalone function.
        """
        auditor = AuditingCallHandler()
        uut = Interposer(standalone_function, auditor)
        assert uut(24) == 42

        calls = auditor.calls
        assert len(calls) == 1

        assert calls[0]["args"] == (24,)
        assert calls[0]["kwargs"] == {}
        assert calls[0]["name"] == "standalone_function"
        assert calls[0]["result"] == 42
        assert "function" in str(calls[0]["type"])

    def test_interposer_properties(self):
        """
        Tests using class properties.
        """
        auditor = AuditingCallHandler()
        uut = Interposer(SimpleClass(), auditor)
        guide = uut.guide
        assert type(guide) == str
        assert isinstance(guide, str)
        assert guide == "DON'T PANIC!"

        jade = uut.jade
        assert type(jade) == str
        assert isinstance(jade, str)

        calls = auditor.calls
        assert len(calls) == 0

    def test_interposer_builtin(self):
        """
        Tests how we handle builtins.
        """
        auditor = AuditingCallHandler()

        assert inspect.isbuiltin(datetime.datetime.utcnow)
        uut = Interposer(datetime.datetime, auditor)
        assert not isinterposed(uut.utcnow())

        calls = auditor.calls
        assert len(calls) == 1

        assert calls[0]["args"] == ()
        assert calls[0]["kwargs"] == {}
        assert calls[0]["name"] == "datetime.utcnow"
        assert isinstance(calls[0]["result"], datetime.datetime)
        assert "builtin_function_or_method" in str(calls[0]["type"])
