# -*- coding: utf-8 -*-
#
# Copyright (c) 2020 Tuono, Inc.
# All Rights Reserved
#
import gzip
import os

from pathlib import Path
from unittest import TestCase

from interposer import Interposer
from interposer import Mode


class InterposedTestCase(TestCase):
    """
    Wraps a test that leverages interposer to record and then play back tests.

    When the environment variable RECORDING is set, the tests in this test
    class will record what they do, depending on what is patched in as a
    wrapper.
    """

    def setUp(self, recordings: Path, cls: Interposer = Interposer) -> None:
        """
        Prepare for recording or playback based on the test name.

        Arguments:
          cls (Interposer): allows subclassing Interposer
          recordings (Path): the location of the recordings
        """
        super().setUp()

        assert recordings, "recordings location must be specified"
        assert isinstance(
            recordings, Path
        ), "recordings location must be a pathlib.Path"

        self.mode = Mode.Recording if os.environ.get("RECORDING") else Mode.Playback
        self.tape = recordings / f"{self.id()}.db"
        if self.mode == Mode.Playback:
            # decompress the recording
            with gzip.open(str(self.tape) + ".gz", "rb") as fin:
                with self.tape.open("wb") as fout:
                    fout.write(fin.read())
        else:
            recordings.mkdir(parents=True, exist_ok=True)

        self.interposer = cls(self.tape, self.mode)
        self.interposer.open()

    def tearDown(self) -> None:
        """
        Finalize recording or playback based on the test name.
        """
        self.interposer.close()
        if self.mode == Mode.Recording:
            # compress the recording
            with self.tape.open("rb") as fin:
                with gzip.open(str(self.tape) + ".gz", "wb") as fout:
                    fout.write(fin.read())

        # self.tape is the uncompressed file - do not leave it around
        self.tape.unlink()

        super().tearDown()
