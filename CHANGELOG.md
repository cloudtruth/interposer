# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0]

### Changed

- Switched from setuptools and tox to poetry for project management.
- Added release workflow.
- Added typing with mypy checks.

## [0.9.3]

### Changed

- Update dependencies.

## [0.9.2] - 2020-10-19

### Changed

- Allow redaction of bytes.

## [0.9.1] - 2020-09-26

### Changed

- When starting a recording, remove any existing uncompressed file.

## [0.9.0] - 2020-09-24

### Breaking

- Fixed inability to playback recordings if the length of any of the
  secrets provided differ at playback time from recording time.  The
  length of redactions provided for playback must be derived from the
  length of the original secret that was redacted.

## [0.8.1] - 2020-09-24

### Changed

- Honor changes call handlers make to args, kwargs in on_call_begin
  so those changes make it to the actual call.

## [0.8.0] - 2020-09-21

This was a major refactoring to allow for custom call handlers.

### Breaking

- Switched from json to pickle based hashing.
- Separated the record/playback logic from the wrapping logic.

### Changed

- Added RecordedTestCase and @recorded decorators for easier testing.
- Added the ability to stack call handlers.
- Allow a call handler to determine if the result of a call gets
  rewrapped (to record calls on the result, i.e. selective diving).
- Added automatic secret redaction from TapeDeck recordings.
- Eliminated special case code for dealing with primitives.

## [0.7.0] - 2020-09-10

### Breaking

- Signatures of most of the cleanup methods have changed.
- `wrap` no longer requires (or accepts) `as_method` for wrapping
  class instantiations.
- `wrap` raises WrappingError if something is not wrappable.

### Changed

- Added support for wrapping modules.
- Added support for wrapping object instantiations from class definitions.
- Added support for builtins.
- Added logging control for wrapping and calling.
- Added support for conditionally replacing original return value with cleaned one.
- Added support for conditionally not recording a call.
- Consolidated determination of whether something is `wrappable`.
- Fixed wrapping of property results.
- Fixed incorrect wrapping of python primitives like `str`.
- Fixed call order parameter storage could be modified after call.

## [0.6.1] - 2020-09-04

### Changed

- `InterposedTestCase` now allows Interposer to be subclassed.

## [0.6.0] - 2020-09-04

### Added

- `InterposedTestCase` was added to make testing even easier.

### Changed

- Updated the README.
- Provided an example.

## [0.5.0] - 2020-09-01

Initial Release.
