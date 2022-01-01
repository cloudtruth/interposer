#
# Copyright (C) 2019 - 2021 Tuono, Inc.
# Copyright (C) 2021 - 2022 CloudTruth, Inc.
#

.PHONY: all clean coverage dist example lint pdb prerequisites setup test test-loop

all: test

clean:
	@rm -f  .coverage
	@rm -rf build
	@rm -f  coverage.xml
	@rm -rf dist
	@find . -name '*.py,cover' | xargs rm -f
	@find . -name '*.pyc' | xargs rm -f
	@find . -name '__pycache__' | xargs rm -rf

coverage:
	poetry run pytest -v --cov --cov-report=term-missing --cov-report=xml

dist: clean
	poetry build

example:
	# requires "make prerequisites" and "make setup" to have been run once before
	# to record: time RECORDING=1 make example
	# to playback: time make example
	# log level 7 includes logging results
	poetry run pytest -o log_cli=true -o log_cli_level=7 tests/example_weather_test.py

lint:
	poetry run pre-commit run -a

pdb:
	poetry run pytest --pdb

# this may require that ~/.local/bin is in your PATH
prerequisites:
	python3 -m pip install -U poetry

setup:
	poetry config virtualenvs.in-project true
	poetry install
	poetry run pre-commit install

test:
	poetry run pytest

test-loop:
	while make test; do :; done

