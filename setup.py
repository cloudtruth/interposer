#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (C) 2019 - 2020 Tuono, Inc.
# All Rights Reserved
#
from pathlib import Path

from setuptools import setup

# Configurables

name = "interposer"
description = "A code intercept wrapper with recording and playback options."
major = 0
minor = 5
patch = 1

# Everything below should be cookie-cutter


def get_requirements(name: str) -> list:
    """
    Return the contents of a requirements file

    Arguments:
      - name: the name of a file in the requirements directory

    Returns:
      - a list of requirements
    """
    return read_file(Path(f"requirements/{name}.txt")).splitlines()


def read_file(path: Path) -> str:
    """
    Return the contents of a file

    Arguments:
      - path: path to the file

    Returns:
      - contents of the file
    """
    with path.open() as desc_file:
        return desc_file.read().rstrip()


requirements = {}
for _type in ["run", "test"]:
    requirements[_type] = get_requirements(_type)

setup(
    name=name,
    version=f"{major}.{minor}.{patch}",
    python_requires=">=3.7.3",
    description=description,
    long_description=read_file(Path("README.md")),
    long_description_content_type="text/markdown",
    classifiers=[
        "Development Status :: 4 - Beta",
        "License :: OSI Approved :: Apache Software License",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Testing :: Mocking",
        "Programming Language :: Python :: 3 :: Only",
    ],
    keywords="testing, record, playback, intercept",
    download_url=f"https://github.com/tuono/{name}",
    url="https://www.tuono.com/",
    author="Tuono, Inc.",
    author_email="dev@tuono.com",
    license=read_file(Path("LICENSE")),
    install_requires=requirements["run"],
    include_package_data=True,
    packages=[name],
)
