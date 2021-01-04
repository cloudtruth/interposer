# interposer

[![Build Status](https://github.com/tuono/interposer/workflows/coverage/badge.svg)](https://github.com/tuono/interposer/actions?query=workflow%3Acoverage)
[![Release Status](https://github.com/tuono/interposer/workflows/release/badge.svg)](https://github.com/tuono/interposer/actions?query=workflow%3Arelease)
[![codecov](https://codecov.io/gh/tuono/interposer/branch/develop/graph/badge.svg?token=HKUTULQQSA)](https://codecov.io/gh/tuono/interposer)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

The interposer package core allows you to wrap a module, class, object, method,
or function with the ability to perform pre- and post- call analysis or
manipulation on the arguments, result, or exception.  This behavior can either
be "always on" (i.e. in production code) or patched in through tests.  With
interposer you can:

- Audit calls made.
- Block calls that should not be made (for example, read-only vs. read-write).
- Modify arguments before calls are made.
- Record and playback interactions with packages for hybrid testing.

Classic unit testing involves writing mocks or simulators for third party
services.  When a service is mocked, the test is typically only as good as
the simulation.  Classic integration testing runs live against a service,
but it can take too long to be useful in normal development workflow.  What
if you could have both?  You can - we call it hybrid testing.

Hybrid testing allows you to test your code live against a third party service
only when necessary and avoid the need to write your own mocks.  It is
essentially a self-writing mock for your interaction.  Service mocks tend to
be incomplete simulations and can lead to a false sense of security, however by
using hybrid testing, you no longer have to worry about that.  Even better, the
provided recording system includes a way to automatically redact secrets and
still be able to play back.  If a live test against a service takes minutes,
it will only take seconds when played back.

## TL;DR;

### Hybrid Testing

To get started with hybrid testing, use the `RecordedTestCase` test fixture.
An example of this can be found in the
[example_weather_test](https://github.com/tuono/interposer/blob/develop/tests/example_weather_test.py).
This is a simple test that demonstrates how easy it is to hook in recording
and playback against an external service.

To generate a recording, `RecordedTestCase` looks for an environment variable
named `RECORDING` and if set (and not empty), will generate a recording of the
interaction with the interposed class(es) automatically:

```bash
$ time RECORDING=1 make example
...
real    0m8.651s
user    0m1.911s
sys     0m0.219s

$ tests/
tests/:
total 44
-rw-r--r-- 1 testr testr    83 Sep 18 13:59 __init__.py
-rw-r--r-- 1 testr testr   535 Sep 18 13:59 example_weather_test.py
-rw-r--r-- 1 testr testr 11795 Sep 18 21:15 interposer_test.py
-rw-r--r-- 1 testr testr  8483 Sep 19 22:44 recorder_test.py
-rw-r--r-- 1 testr testr  8152 Sep 19 22:44 tapedeck_test.py
drwxr-xr-x 3 testr testr  4096 Sep 20 07:57 tapes

tests/tapes:
total 4
drwxr-xr-x 2 testr testr 4096 Sep 20 07:29 example_weather_test

tests/tapes/example_weather_test:
total 4
-rw-r--r-- 1 testr testr 1678 Sep 20 07:14 TestWeather.db.gz
```

Once the recording is generated, running the test again without the
environment variable causes the playback to happen:

```bash
$ time tox example_weather_test.py
...
real    0m2.039s
user    0m1.822s
sys     0m0.212s
```

Given tox has a roughly 2 second startup time, we see the playback is
essentially as fast as a handcrafted mock, but took way less time to make!
More details can be found in the Recording and Playback section below.

## Background

At Tuono when we first started working with the AWS and Azure SDKs, we
realized that it would not be practical to mock those services in our
tests.  Mocking a complex multi-step interaction with a third party service
such as a cloud provider can be very time-consuming and error-prone.
Entire projects already exist which attempt to mock these service interfaces,
and those projects are both incomplete and incorrect at any given time.
Maintaining such a footprint requires tremendous effort, and if the mock
responses are not correct, it leads to a false sense of code quality which
can then fail in front of a customer when used against the real thing.

Some may argue that separate integration testing would catch this failure mode,
however that defers the problem until after the code is developed and mocked,
which makes it more expensive to remedy.  We started to wonder if there was
a way to mix unit testing and integration testing to solve this problem.

These learnings have led us to the interposer - a python package designed to
allow the engineer to patch a recording and playback system into production
code, and then replay the interaction in future runs.  The benefits here are
tremendous for testing complex external services:

- The complete interaction with the external service is recorded and can be
  faithfully played back.
- Ensures future code changes will not break your interactions.
- Complex operations that require significant time to run during recording
  have no such delays during playback because it never actually goes out to
  the external service.
- Testing real interactions with external services can be done in isolation,
  without loading the entire project.

## Recording and Playback

Interposer can be used in place of a mock to record and playback interactions.
There is a simple example in this repository of a Weather object that
leverages an external service.  Mocking this service would take time, as the
response is fairly complex, but with interposer it's as easy as adding a patch.

RecordedTestCase is a testing class that makes it easy to manage your
recordings automatically based on the name of the test module, class, and tests.
Each test class receives its own recording file, and each test method is recorded
into its own channel within the recording file, so it is safe to use in
parallel testing.  This example test case inserts itself between the Weather
class and the `noaa` class that it uses.

```python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2020 Tuono, Inc.
# All Rights Reserved
#
from noaa_sdk import noaa

from interposer.example.weather import Weather
from interposer.recorder import recorded
from interposer.recorder import RecordedTestCase


class TestWeather(RecordedTestCase):
    """ Example of a record/playback aware test. """

    @recorded(patches={"interposer.example.weather.noaa": noaa})
    def test_print_forecast(self) -> None:
        uut = Weather()
        assert len(uut.forecast("01001", "US", False, 3)) == 3
```

To generate a recording (this works if you "make prerequisites" first):

```bash
$ time RECORDING=1 make example
...
tests/example_weather_test.py::TestWeather::test_print_forecast
------------------------------------------------------------------------------------------------- live log call -------------------------------------------------------------------------------------------------
INFO     interposer.interposer:interposer.py:147 TAPE: Opened /home/testr/interposer/tests/tapes/example_weather_test.TestWeather.test_print_forecast.db for Mode.Recording using version 5
DEBUG    urllib3.connectionpool:connectionpool.py:943 Starting new HTTPS connection (1): nominatim.openstreetmap.org:443
DEBUG    urllib3.connectionpool:connectionpool.py:442 https://nominatim.openstreetmap.org:443 "GET //search?postalcode=11365&country=US&format=json HTTP/1.1" 200 None
DEBUG    urllib3.connectionpool:connectionpool.py:943 Starting new HTTPS connection (1): api.weather.gov:443
DEBUG    urllib3.connectionpool:connectionpool.py:442 https://api.weather.gov:443 "GET //points/40.73874584464741,-73.79325760300824 HTTP/1.1" 301 481
DEBUG    urllib3.connectionpool:connectionpool.py:442 https://api.weather.gov:443 "GET /points/40.7387,-73.7933 HTTP/1.1" 200 810
DEBUG    urllib3.connectionpool:connectionpool.py:943 Starting new HTTPS connection (1): api.weather.gov:443
DEBUG    urllib3.connectionpool:connectionpool.py:442 https://api.weather.gov:443 "GET //gridpoints/OKX/39,36/forecast HTTP/1.1" 200 1428
DEBUG    interposer.interposer:interposer.py:361 TAPE: Recording RESULT 25c0bc73bd753f18e53c1b803d8d37e2ce8a7d7a.results call #0 for params {'method': 'get_forecasts', 'args': ('11365', 'US', False), 'kwargs': {}, 'channel': 'default'} hash=25c0bc73bd753f18e53c1b803d8d37e2ce8a7d7a type=list: [{'detailedForecast': 'Partly cloudy, with a low around 72. West wind around 8 '
...
{'number': 1, 'name': 'Overnight', 'startTime': '2020-09-04T04:00:00-04:00', 'endTime': '2020-09-04T06:00:00-04:00', 'isDaytime': False, 'temperature': 72, 'temperatureUnit': 'F', 'temperatureTrend': None, 'windSpeed': '8 mph', 'windDirection': 'W', 'icon': 'https://api.weather.gov/icons/land/night/sct?size=medium', 'shortForecast': 'Partly Cloudy', 'detailedForecast': 'Partly cloudy, with a low around 72. West wind around 8 mph.'}
{'number': 2, 'name': 'Friday', 'startTime': '2020-09-04T06:00:00-04:00', 'endTime': '2020-09-04T18:00:00-04:00', 'isDaytime': True, 'temperature': 87, 'temperatureUnit': 'F', 'temperatureTrend': 'falling', 'windSpeed': '8 to 13 mph', 'windDirection': 'W', 'icon': 'https://api.weather.gov/icons/land/day/sct?size=medium', 'shortForecast': 'Mostly Sunny', 'detailedForecast': 'Mostly sunny. High near 87, with temperatures falling to around 84 in the afternoon. West wind 8 to 13 mph.'}
{'number': 3, 'name': 'Friday Night', 'startTime': '2020-09-04T18:00:00-04:00', 'endTime': '2020-09-05T06:00:00-04:00', 'isDaytime': False, 'temperature': 66, 'temperatureUnit': 'F', 'temperatureTrend': None, 'windSpeed': '8 to 12 mph', 'windDirection': 'NW', 'icon': 'https://api.weather.gov/icons/land/night/few?size=medium', 'shortForecast': 'Mostly Clear', 'detailedForecast': 'Mostly clear, with a low around 66. Northwest wind 8 to 12 mph.'}
INFO     interposer.interposer:interposer.py:158 TAPE: Closed /home/testr/interposer/tests/tapes/example_weather_test.TestWeather.test_print_forecast.db for Mode.Recording using version 5
PASSED

=============================================================================================== 1 passed in 6.65s ===============================================================================================
____________________________________________________________________________________________________ summary ____________________________________________________________________________________________________
  py37: commands succeeded
  congratulations :)

real    0m8.651s
user    0m1.911s
sys     0m0.219s
```

Note the calls to urllib3 used by the noaa class, and note the amount of time
that the test ran.  This command produced a new file:

```bash
$ ls tests/tapes/example_weather_test
tests/tapes/example_weather_test:
total 4
-rw-r--r-- 1 testr testr 1678 Sep 20 07:14 TestWeather.db.gz
```

Now that the recording is in place, any time the test runs in the future it
will avoid actually calling the noaa class, but instead use a recorded
response that matches the method and parameters:

```bash
$ time make example
...
tests/example_weather_test.py::TestWeather::test_print_forecast
------------------------------------------------------------------------------------------------- live log call -------------------------------------------------------------------------------------------------
INFO     interposer.interposer:interposer.py:147 TAPE: Opened /home/testr/interposer/tests/tapes/example_weather_test.TestWeather.test_print_forecast.db for Mode.Playback using version 5
DEBUG    interposer.interposer:interposer.py:313 TAPE: Playing back RESULT for 25c0bc73bd753f18e53c1b803d8d37e2ce8a7d7a.results call #0 for params {'method': 'get_forecasts', 'args': ('11365', 'US', False), 'kwargs': {}, 'channel': 'default'} hash=25c0bc73bd753f18e53c1b803d8d37e2ce8a7d7a type=list: [{'detailedForecast': 'Partly cloudy, with a low around 72. West wind around 8 '
{'number': 1, 'name': 'Overnight', 'startTime': '2020-09-04T04:00:00-04:00', 'endTime': '2020-09-04T06:00:00-04:00', 'isDaytime': False, 'temperature': 72, 'temperatureUnit': 'F', 'temperatureTrend': None, 'windSpeed': '8 mph', 'windDirection': 'W', 'icon': 'https://api.weather.gov/icons/land/night/sct?size=medium', 'shortForecast': 'Partly Cloudy', 'detailedForecast': 'Partly cloudy, with a low around 72. West wind around 8 mph.'}
{'number': 2, 'name': 'Friday', 'startTime': '2020-09-04T06:00:00-04:00', 'endTime': '2020-09-04T18:00:00-04:00', 'isDaytime': True, 'temperature': 87, 'temperatureUnit': 'F', 'temperatureTrend': 'falling', 'windSpeed': '8 to 13 mph', 'windDirection': 'W', 'icon': 'https://api.weather.gov/icons/land/day/sct?size=medium', 'shortForecast': 'Mostly Sunny', 'detailedForecast': 'Mostly sunny. High near 87, with temperatures falling to around 84 in the afternoon. West wind 8 to 13 mph.'}
{'number': 3, 'name': 'Friday Night', 'startTime': '2020-09-04T18:00:00-04:00', 'endTime': '2020-09-05T06:00:00-04:00', 'isDaytime': False, 'temperature': 66, 'temperatureUnit': 'F', 'temperatureTrend': None, 'windSpeed': '8 to 12 mph', 'windDirection': 'NW', 'icon': 'https://api.weather.gov/icons/land/night/few?size=medium', 'shortForecast': 'Mostly Clear', 'detailedForecast': 'Mostly clear, with a low around 66. Northwest wind 8 to 12 mph.'}
INFO     interposer.interposer:interposer.py:158 TAPE: Closed /home/testr/interposer/tests/tapes/example_weather_test.TestWeather.test_print_forecast.db for Mode.Playback using version 5
PASSED

=============================================================================================== 1 passed in 0.06s ===============================================================================================
____________________________________________________________________________________________________ summary ____________________________________________________________________________________________________
  py37: commands succeeded
  congratulations :)

real    0m2.039s
user    0m1.822s
sys     0m0.212s
```

Recording has advantages and disadvantages, so the right solution
for your situation depends on many things.  Recording eliminates
the need to produce and maintain mocks.  Mocks of third party
libraries that change or are not well understood are fragile and
lead to a false sense of safety.  Recordings on the other hand
are always correct, but they need to be regenerated when your
logic changes around the third party calls.

## Restrictions

- Return values and exceptions must be safe for pickling.  Some
  third party APIs use local definitions for exceptions, for example,
  and local definitions cannot be pickled.  If you get a pickling
  error, you can insert a CallHandler to run before the TapeDeckCallHandler
  by specifying `prehandlers` in the @recorded decorator.
- Randomness between test runs generally defeats recording and playback,
  however you can record the randomness!

## Dealing with Randomness

If you have code that uses the uuid package to generate unique IDs,
and those IDs end up in parameters used by the class being recorded,
the same IDs need to be used during playback.  The same issue occurs
with time-based identifiers.  The easiest way to get around this is to
record the randomness!

```python
import uuid

from some.example.project.randomness import Randomness
from interposer.recorder import RecordedTestCase
from interposer.recorder import recorder

class TestRandomness(RecordedTestCase):

    @recorded(patches={"some.example.project.randomness.uuid.uuid4": uuid.uuid4})
    def test_uuid(self) -> None:
        uut = Randomness()
        uut.call_a_method_that_uses_uuids()
```

In this fictituous and non-working example (some.example.project is not
provided), calls to create uuids would be recorded.

## Call Auditing

Use the Interposer to wrap a module, class, object, method, or function with
a CallHandler that reports all the calls to an auditing service.

To facilitate auditing and call verification, use Interposer directly in
your production code.  Interposer leverages the fantastic
[wrapt](https://github.com/GrahamDumpleton/wrapt) package to provide
doppleganger support, with almost no performance degradation.

## Call Blocking

You may want to limit the types of methods that can be called in
third party libraries as an extra measure of protection in certain
runtime modes.  Interposer lets you intercept every method called
in a wrapped class.  You just have to implement a CallHandler and
then wrap the module, class, object, method, or function you want to
raise an exception when a call is not allowed.

## Secrets!

The recording system has a built-in secrets redacter.  In a test method, before
a secret is used, call `self.redact(secret)`.  If the tape deck is in recording
mode, the secret is passed to the tape deck for redaction.  This means:

1. The real secret is passed to the actual call during recording.
2. The secret is then replaced by typesafe redaction holistically and reliably
   in the argument list, and result or exception so the secret can never exist
   in the recording file.
3. The recording's call signature is calculated with redacted secrets so that
   when redacted secrets are used during playback, the calls can be found.

In playback mode, call `self.redact(secret)` and it will return a redacted
string for you to use in place of the secret.  This allows the playback call
signatures to match the recorded call signatures.

## Misaligned Playback

If code or libraries change, the recording may no longer match the call
patterns.  When you see a `RecordedCallNotFoundError` you should try to
regenerate your recording.  If this does not work, there is likely a piece
of information in the recording that is not idempotent, such as a timestamp
or a uuid.

If you set the logging level to 7 (more than DEBUG, which is 10), any mismatch
encountered during playback will be accompanied by a "diff" of the
recorded call and the requested playback call, for example:

    $ tox -e debug <testname> -- --pdb -s -o log_cli=True -o log_cli_level=7
