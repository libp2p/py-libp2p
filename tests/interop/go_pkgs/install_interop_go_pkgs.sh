#!/bin/bash

SCRIPT_RELATIVE_PATH=`dirname $0`

GO_PKGS_PATH=$SCRIPT_RELATIVE_PATH

DAEMON_REPO=go-libp2p-daemon
DAEMON_BRANCH=v0.2.4
DAEMON_PATH=$GO_PKGS_PATH/$DAEMON_REPO

EXAMPLES_PATHS=$GO_PKGS_PATH/examples

go version

# Install `p2pd`
# FIXME: Use the canonical repo in libp2p, when we don't need `insecure`.
if [ ! -e "$DAEMON_PATH" ]; then
    git clone https://github.com/libp2p/$DAEMON_REPO.git --branch $DAEMON_BRANCH $DAEMON_PATH
    if [ "$?" != 0 ]; then
        echo "Failed to clone the daemon repo"
        exit 1
    fi
fi

cd $DAEMON_PATH && go install ./...

cd -

# Install example modeuls
cd $EXAMPLES_PATHS && go install ./...

echo "Finish installing go modules for interop."
