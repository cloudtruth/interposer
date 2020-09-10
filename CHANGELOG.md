# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.7.0] - 2019-09-10

### Breaking

- `wrap` no longer requires (or accepts) `as_method` for wrapping
  class instantiations.
- `wrap` raises WrappingError if something is not wrappable.

### Changed

- Added support for wrapping modules.
- Added support for wrapping object instantiations from class definitions.
- Added logging control for wrapping and calling.
- Consolidated determination of whether something is `wrappable`.
- Fixed wrapping of property results.
- Fixed unnecessary wrapping of python primitives like `str`.

## [0.6.1] - 2019-09-04

### Changed

- `InterposedTestCase` now allows Interposer to be subclassed.

## [0.6.0] - 2019-09-04

### Added

- `InterposedTestCase` was added to make testing even easier.

### Changed

- Updated the README.
- Provided an example.

## [0.5.0] - 2019-09-01

Initial Release.
