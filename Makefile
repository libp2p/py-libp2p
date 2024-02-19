CURRENT_SIGN_SETTING := $(shell git config commit.gpgSign)

.PHONY: clean-pyc clean-build docs

help:
	@echo "clean-build - remove build artifacts"
	@echo "clean-pyc - remove Python file artifacts"
	@echo "lint - fix linting issues with pre-commit"
	@echo "test - run tests quickly with the default Python"
	@echo "docs - generate docs and open in browser (linux-docs for version on linux)"
	@echo "notes - consume towncrier newsfragments/ and update release notes in docs/"
	@echo "release - package and upload a release (does not run notes target)"
	@echo "dist - package"

FILES_TO_LINT = libp2p tests tests_interop examples setup.py
PB = libp2p/crypto/pb/crypto.proto \
	libp2p/pubsub/pb/rpc.proto \
	libp2p/security/insecure/pb/plaintext.proto \
	libp2p/security/secio/pb/spipe.proto \
	libp2p/security/noise/pb/noise.proto \
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

clean-pyc:
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -rf {} +

lint:
	@pre-commit run --all-files --show-diff-on-failure || ( \
		echo "\n\n\n * pre-commit should have fixed the errors above. Running again to make sure everything is good..." \
		&& pre-commit run --all-files --show-diff-on-failure \
	)

test:
	pytest tests

build-docs:
	sphinx-apidoc -o docs/ . setup.py "*conftest*" "libp2p/tools/interop*"
	$(MAKE) -C docs clean
	$(MAKE) -C docs html
	$(MAKE) -C docs doctest
	
build-docs-ci:
	$(MAKE) -C docs latexpdf
	$(MAKE) -C docs epub

validate-newsfragments:
	python ./newsfragments/validate_files.py
	towncrier build --draft --version preview

check-docs: build-docs validate-newsfragments

check-docs-ci: build-docs build-docs-ci validate-newsfragments

docs: check-docs
	open docs/_build/html/index.html

linux-docs: check-docs
	xdg-open docs/_build/html/index.html

package: clean
	python setup.py sdist bdist_wheel
	python scripts/release/test_package.py

notes:
check-bump:
ifndef bump
	$(error bump must be set, typically: major, minor, patch, or devnum)
endif

notes: check-bump
	# Let UPCOMING_VERSION be the version that is used for the current bump
	$(eval UPCOMING_VERSION=$(shell bumpversion $(bump) --dry-run --list | grep new_version= | sed 's/new_version=//g'))
	# Now generate the release notes to have them included in the release commit
	towncrier build --yes --version $(UPCOMING_VERSION)
	# Before we bump the version, make sure that the towncrier-generated docs will build
	make build-docs
	git commit -m "Compile release notes for v$(UPCOMING_VERSION)"

release: check-bump clean
	# require that upstream is configured for ethereum/py-libp2p
	@git remote -v | grep -E "upstream\tgit@github.com:ethereum/py-libp2p.git \(push\)|upstream\thttps://(www.)?github.com/ethereum/py-libp2p \(push\)"
	# verify that docs build correctly
	./newsfragments/validate_files.py is-empty
	make build-docs
	CURRENT_SIGN_SETTING=$(git config commit.gpgSign)
	git config commit.gpgSign true
	bumpversion $(bump)
	git push upstream && git push upstream --tags
	python -m build
	twine upload dist/*
	git config commit.gpgSign "$(CURRENT_SIGN_SETTING)"


dist: clean
	python -m build
	ls -l dist
