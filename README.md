# interposer

[![Build Status](https://github.com/tuono/interposer/workflows/coverage/badge.svg)](https://github.com/tuono/interposer/actions?query=workflow%3Acoverage)
[![Release Status](https://github.com/tuono/interposer/workflows/release/badge.svg)](https://github.com/tuono/interposer/actions?query=workflow%3Arelease)
[![codecov](https://codecov.io/gh/tuono/interposer/branch/master/graph/badge.svg?token=HKUTULQQSA)](https://codecov.io/gh/tuono/interposer)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

This library lets you wrap any class or bare function and:

1. Record all the method calls (parameters, return values, exceptions).
2. Playback all the method calls.
3. Inspect the method calls to ensure they meet certain criteria.

## Record and Playback

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

## Call Inspection

You may want to limit the types of methods that can be called in
third party libraries as an extra measure of protection in certain
runtime modes.  Interposer lets you intercept every method called
in a wrapped class.

## Usage

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

In most cases you want to leverage environment variables with
your own method that retrieves a class, for example if you want
to wrap the AWS boto3 library:

    import boto3
    import interposer
    import os

    if os.get("RECORDING_FILE"):
        global client_args
        wrapper = interposer.Interposer(os.get("RECORDING_FILE"), interposer.Mode.Recording)
        client = boto3.client("ec2", **client_args)
        wrapped_client = wrapper.wrap(client)
        return wrapped_client

Now any method call on `client` will be recorded.  To play back the same
stream with the same code, change the interposer mode to Playback and re-run
the code.  Instead of calling boto3, the interposer will intercept and provide
the same return values or exceptions that boto3 provided during recording for
given combinations of method names and parameters.

## Restrictions

- Return values and Exceptions must be safe for pickling.  Some
  third party APIs use local definitions for exceptions, for example,
  and local definitions cannot be pickled.  If you get a pickling
  error, you should subclass Interposer and provide your own
  cleanup routine(s) as needed to substitute a class that can be
  substituted for the local definition.

## Notes

- This is a resource, so you need to call open() and close() or
  use the ScopedInterposer context manager.
- The class variables are ignored for purposes of hashing the
  method calls into unique signatures (channel name + method name
  + parameters).

This documentation is not complete, for example pre and post cleanup
mechanisms are not documented, nor is the security check for call inspection.
