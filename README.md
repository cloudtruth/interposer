# interposer

[![Build Status](https://github.com/tuono/interposer/workflows/coverage/badge.svg)](https://github.com/tuono/interposer/actions?query=workflow%3Acoverage)
[![Release Status](https://github.com/tuono/interposer/workflows/release/badge.svg)](https://github.com/tuono/interposer/actions?query=workflow%3Arelease)
[![codecov](https://codecov.io/gh/tuono/interposer/branch/develop/graph/badge.svg?token=HKUTULQQSA)](https://codecov.io/gh/tuono/interposer)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

Interposer allows you to add selective recording and playback of interactions
with external services that are too complex to mock effectively.  Interposer
allows you to:

- Inject recording and playback into production code through tests -
  sort of like mocks with a memory.
- Audit external service calls.
- Prevent unwanted future external service calls.

## TL;DR;

### Testing

To inject recording and playback into your tests, use the InterposerTestCase
class and patch interposed versions of external services.  An example of this
can be found in the [example_weather_test](https://github.com/tuono/interposer/blob/develop/tests/example_weather_test.py),
which tests [weather.py](https://github.com/tuono/interposer/blob/develop/interposer/_testing/weather.py).

To generate a recording, InterposerTestCase looks for an environment variable
named RECORDING and if set (and not empty), will generate a recording of the
interaction with the interposed class(es):

```
$ time RECORDING=1 tox example_weather_test.py
...
real    0m8.651s
user    0m1.911s
sys     0m0.219s

$ ls tapes
example_weather_test.TestWeather.test_print_forecast.db.gz
```

Once the recording is generated, running the test again without the
environment variable causes the playback to happen:

```
$ time tox example_weather_test.py
...
real    0m2.039s
user    0m1.822s
sys     0m0.212s
```

Given tox has a roughly 2 second startup time, we see the playback is
essentially as fast as a handcrafted mock, but took less time to make!
More details can be found in the Recording and Playback section below.

### Auditing

To facilitate auditing and call verification, use Interposer directly in
your production code.  Interposer uses the
[wrapt](https://github.com/GrahamDumpleton/wrapt) package to provide
doppleganger support, with little noticable performance degradation.

## Introduction

At Tuono when we first started working with the AWS and Azure SDKs, we
realized that it would not be practical to mock those services in our
tests.  Mocking a complex multi-step interaction with a third party service
such as a cloud provider can be very time-consuming and error-prone.
Entire projects already exist which attempt to mock these service interfaces.
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

InterposedTestCase is a testing class that makes it easy to manage your
recordings automatically based on the name of the test module, class, and tests.
Each test definition receives its own recording file so it is safe to use with
parallel testing.  This example test case inserts itself between the Weather
class and the `noaa` class that it uses.

```python
from pathlib import Path
from unittest.mock import patch

from noaa_sdk import noaa

from interposer import InterposedTestCase
from interposer._testing.weather import Weather

class TestWeather(InterposedTestCase):
    def setUp(self) -> None:
        super().setUp(recordings=Path(__file__).parent / "tapes")

    def test_print_forecast(self) -> None:
        """
        Inserts the interposer between the importing class
        and the imported class.
        """
        with patch(
            "interposer._testing.weather.noaa",
            new=self.interposer.wrap(noaa)
        ):
            uut = Weather()
            uut.print_forecast("11365", "US", False, 3)
```

The class `InterposedTestCase` is a convenience wrapper around the Interposer
and generates recording files (or plays them back) based on the test id.  This
makes it safe to run recording and playback with interposer in parallel.

To generate a recording (this works if you "make prerequisites" first):

```bash
$ time RECORDING=1 make example
...
tests/example_weather_test.py::TestWeather::test_print_forecast
------------------------------------------------------------------------------------------------- live log call -------------------------------------------------------------------------------------------------
INFO     interposer.interposer:interposer.py:147 TAPE: Opened /home/jking/interposer/tests/tapes/example_weather_test.TestWeather.test_print_forecast.db for Mode.Recording using version 5
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
INFO     interposer.interposer:interposer.py:158 TAPE: Closed /home/jking/interposer/tests/tapes/example_weather_test.TestWeather.test_print_forecast.db for Mode.Recording using version 5
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
$ ls tapes
example_weather_test.TestWeather.test_print_forecast.db.gz
```

Now that the recording is in place, any time the test runs in the future it
will avoid actually calling the noaa class, but instead use a recorded
response that matches the method and parameters:

```bash
$ time make example
...
tests/example_weather_test.py::TestWeather::test_print_forecast
------------------------------------------------------------------------------------------------- live log call -------------------------------------------------------------------------------------------------
INFO     interposer.interposer:interposer.py:147 TAPE: Opened /home/jking/interposer/tests/tapes/example_weather_test.TestWeather.test_print_forecast.db for Mode.Playback using version 5
DEBUG    interposer.interposer:interposer.py:313 TAPE: Playing back RESULT for 25c0bc73bd753f18e53c1b803d8d37e2ce8a7d7a.results call #0 for params {'method': 'get_forecasts', 'args': ('11365', 'US', False), 'kwargs': {}, 'channel': 'default'} hash=25c0bc73bd753f18e53c1b803d8d37e2ce8a7d7a type=list: [{'detailedForecast': 'Partly cloudy, with a low around 72. West wind around 8 '
{'number': 1, 'name': 'Overnight', 'startTime': '2020-09-04T04:00:00-04:00', 'endTime': '2020-09-04T06:00:00-04:00', 'isDaytime': False, 'temperature': 72, 'temperatureUnit': 'F', 'temperatureTrend': None, 'windSpeed': '8 mph', 'windDirection': 'W', 'icon': 'https://api.weather.gov/icons/land/night/sct?size=medium', 'shortForecast': 'Partly Cloudy', 'detailedForecast': 'Partly cloudy, with a low around 72. West wind around 8 mph.'}
{'number': 2, 'name': 'Friday', 'startTime': '2020-09-04T06:00:00-04:00', 'endTime': '2020-09-04T18:00:00-04:00', 'isDaytime': True, 'temperature': 87, 'temperatureUnit': 'F', 'temperatureTrend': 'falling', 'windSpeed': '8 to 13 mph', 'windDirection': 'W', 'icon': 'https://api.weather.gov/icons/land/day/sct?size=medium', 'shortForecast': 'Mostly Sunny', 'detailedForecast': 'Mostly sunny. High near 87, with temperatures falling to around 84 in the afternoon. West wind 8 to 13 mph.'}
{'number': 3, 'name': 'Friday Night', 'startTime': '2020-09-04T18:00:00-04:00', 'endTime': '2020-09-05T06:00:00-04:00', 'isDaytime': False, 'temperature': 66, 'temperatureUnit': 'F', 'temperatureTrend': None, 'windSpeed': '8 to 12 mph', 'windDirection': 'NW', 'icon': 'https://api.weather.gov/icons/land/night/few?size=medium', 'shortForecast': 'Mostly Clear', 'detailedForecast': 'Mostly clear, with a low around 66. Northwest wind 8 to 12 mph.'}
INFO     interposer.interposer:interposer.py:158 TAPE: Closed /home/jking/interposer/tests/tapes/example_weather_test.TestWeather.test_print_forecast.db for Mode.Playback using version 5
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
  error, you should subclass Interposer and provide your own
  cleanup routine(s) as needed to substitute a class that can be
  substituted for the local definition.
- Randomness between test runs generally defeats the interposer, however
  you can record the randomness.

## Dealing with Randomness

If you have code that uses the uuid package to generate unique IDs,
and those IDs end up in parameters used by the class being recorded,
the same IDs need to be used during playback.  The same issue occurs
with time-based identifiers.  The easiest way to get around this is to
record the randomness!

```python
from uuid import uuid4

from some.example.project.randomness import Randomness
from interposer.testcase import InterposedTestCase

class TestRandomness(InterposedTestCase):
    def test_uuid(self) -> None:
        with patch(
            "some.example.project.randomness.uuid4",
            new=self.interposer.wrap(uuid4)
        ):
            uut = Randomness()
            uut.call_a_method_that_uses_uuids()
```

In this fictituous and non-working example (some.example.project is not
provided), calls to create uuids would be recorded.  You can stack
interposed patches so that you can record the external service class as
well as uuid at the same time.


## Call Auditing

You may want to limit the types of methods that can be called in
third party libraries as an extra measure of protection in certain
runtime modes.  Interposer lets you intercept every method called
in a wrapped class.

TODO: provide example!

## Notes

- Interposer is a resource, so you need to call open() and close() or
  use the ScopedInterposer context manager.

This documentation is not complete, for example pre and post cleanup
mechanisms are not documented, nor is the security check for call inspection.
