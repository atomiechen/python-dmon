#!/usr/bin/env bash

set -e
set -x

ruff check src tests
ruff format src tests --check --diff
