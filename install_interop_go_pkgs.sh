#!/bin/bash

GO_PKGS_PATH=./tests/interop/go_pkgs

DAEMON_REPO=go-libp2p-daemon
DAEMON_PATH=$GO_PKGS_PATH/$DAEMON_REPO

EXAMPLES_PATHS=$GO_PKGS_PATH/examples


go version

# Install `p2pd`
# FIXME: Use the canonical repo in libp2p, when we don't need `insecure`.
if [ ! -e "$DAEMON_PATH" ]; then
    git clone git@github.com:mhchia/$DAEMON_REPO.git --branch test/add-options $DAEMON_PATH
fi
cd $DAEMON_PATH
go install ./...

cd -

# Install example modeuls
cd $EXAMPLES_PATHS
go install ./...

echo "Finish installing go modeuls for interop."
