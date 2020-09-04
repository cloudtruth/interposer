#
# Copyright (C) 2019 - 2020 Tuono, Inc.
# All Rights Reserved
#

PROJECT := interposer

STAGEDIR := ~/.cache/pypiserver/$(PROJECT)

.PHONY: all clean dist example pdb prerequisites shell stage test test-loop test-setup

all: test

clean:
	@rm -rf .coverage*
	@rm -rf .tox
	@rm -rf build
	@rm -f  coverage.xml
	@rm -rf dist
	@find . -name '*.py,cover' | xargs rm -f
	@find . -name '*.pyc' | xargs rm -f
	@find . -name '__pycache__' | xargs rm -rf

coverage:
	tox -e coverage

dist: clean
	STAGEDIR=$(STAGEDIR) python3 setup.py sdist

example:
	tox -- -rsx tests/example_weather_test.py

pdb:
	tox -- --pdb

prerequisites:
	python3 -m pip install --user -r requirements/build.txt
	@if [ -z `which pre-commit` ]; then \
	    echo "Add $HOME/.local/bin to your path (try source ~/.profile) and make prerequisites again."; exit 1; fi
	pre-commit install

stage: dist
	@mkdir -p $(STAGEDIR)
	cp -p dist/* $(STAGEDIR)
	@ls -ls $(STAGEDIR)

stage-clean:
	@rm -rf $(STAGEDIR)

test: test-setup
	tox

test-loop:
	while make test; do :; done

test-setup:
	python3 setup.py check
