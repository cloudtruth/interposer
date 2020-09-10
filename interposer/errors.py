# -*- coding: utf-8 -*-
#
# Copyright (C) 2019 - 2020 Tuono, Inc.
# All Rights Reserved
#
class InterposerError(RuntimeError):
    """
    Base class for all interposer errors.
    """


class PlaybackError(InterposerError):
    """
    The interposer never recorded a method call with the parameters given,
    or the sequence of calls somehow changed between recording and playback.

    The recording needs to be regenerated due to code changes.
    """

    pass


class WrappingError(InterposerError):
    """
    Something could not be captured.
    """

    pass
