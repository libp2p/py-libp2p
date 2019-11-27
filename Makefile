CURRENT_SIGN_SETTING := $(shell git config commit.gpgSign)

.PHONY: clean-pyc clean-build docs

help:
	@echo "clean-build - remove build artifacts"
	@echo "clean-pyc - remove Python file artifacts"
	@echo "lint - check style with flake8, etc"
	@echo "lint-roll - auto-correct styles with isort, black, docformatter, etc"
	@echo "test - run tests quickly with the default Python"
	@echo "testall - run tests on every Python version with tox"
	@echo "release - package and upload a release"
	@echo "dist - package"

FILES_TO_LINT = libp2p tests tests_interop examples setup.py
PB = libp2p/crypto/pb/crypto.proto \
	libp2p/pubsub/pb/rpc.proto \
	libp2p/security/insecure/pb/plaintext.proto \
	libp2p/security/secio/pb/spipe.proto \
	libp2p/identity/identify/pb/identify.proto
PY = $(PB:.proto=_pb2.py)
PYI = $(PB:.proto=_pb2.pyi)

# Set default to `protobufs`, otherwise `format` is called when typing only `make`
all: protobufs

protobufs: $(PY)

%_pb2.py: %.proto
	protoc --python_out=. --mypy_out=. $<

clean-proto:
	rm -f $(PY) $(PYI)

clean: clean-build clean-pyc

clean-build:
	rm -fr build/
	rm -fr dist/
	rm -fr *.egg-info

clean-pyc:
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -rf {} +

lint:
	mypy -p libp2p -p examples --config-file mypy.ini
	flake8 $(FILES_TO_LINT)
	black --check $(FILES_TO_LINT)
	isort --recursive --check-only --diff $(FILES_TO_LINT)
	docformatter --pre-summary-newline --check --recursive $(FILES_TO_LINT)
	tox -elint  # This is probably redundant, but just in case...

lint-roll:
	isort --recursive $(FILES_TO_LINT)
	black $(FILES_TO_LINT)
	docformatter -ir --pre-summary-newline $(FILES_TO_LINT)
	$(MAKE) lint

test:
	pytest tests

test-all:
	tox

build-docs:
	sphinx-apidoc -o docs/ . setup.py "*conftest*" "libp2p/tools/interop*"
	$(MAKE) -C docs clean
	$(MAKE) -C docs html
	$(MAKE) -C docs doctest
	./newsfragments/validate_files.py
	towncrier --draft --version preview

docs: build-docs
	open docs/_build/html/index.html

linux-docs: build-docs
	xdg-open docs/_build/html/index.html

package: clean
	python setup.py sdist bdist_wheel
	python scripts/release/test_package.py

notes:
	# Let UPCOMING_VERSION be the version that is used for the current bump
	$(eval UPCOMING_VERSION=$(shell bumpversion $(bump) --dry-run --list | grep new_version= | sed 's/new_version=//g'))
	# Now generate the release notes to have them included in the release commit
	towncrier --yes --version $(UPCOMING_VERSION)
	# Before we bump the version, make sure that the towncrier-generated docs will build
	make build-docs
	git commit -m "Compile release notes"

release: clean
	# require that you be on a branch that's linked to upstream/master
	git status -s -b | head -1 | grep "\.\.upstream/master"
	# verify that docs build correctly
	./newsfragments/validate_files.py is-empty
	make build-docs
	CURRENT_SIGN_SETTING=$(git config commit.gpgSign)
	git config commit.gpgSign true
	bumpversion $(bump)
	git push upstream && git push upstream --tags
	python setup.py sdist bdist_wheel
	twine upload dist/*
	git config commit.gpgSign "$(CURRENT_SIGN_SETTING)"


dist: clean
	python setup.py sdist bdist_wheel
	ls -l dist
