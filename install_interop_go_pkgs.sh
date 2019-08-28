#!/bin/bash

which go
if [ $? != 0 ]; then
    wget https://dl.google.com/go/go1.12.6.linux-amd64.tar.gz
    sudo tar -C /usr/local -xzf $GOPACKAGE
    export GOPATH=$HOME/go
    export GOROOT=/usr/local/go
fi

go version
cd tests/interop/go_pkgs/
go install ./...
