// Minimal go-libp2p WebTransport interop harness for py-libp2p's test suite.
//
// Modes:
//
//	./harness listen          — listen on an OS-chosen UDP port, print
//	                            "LISTEN <multiaddr-with-/p2p/>" once per
//	                            address, then "CONNECTED <peer>" for each
//	                            secured inbound connection.
//	./harness dial <addr>     — dial a /quic-v1/webtransport multiaddr,
//	                            print "DIAL_OK <peer>" and exit 0.
//
// Uses WebTransport only (ALPN h3); no native quic-v1 / TCP.
package main

import (
	"context"
	"fmt"
	"os"
	"time"

	"github.com/libp2p/go-libp2p"
	"github.com/libp2p/go-libp2p/core/network"
	"github.com/libp2p/go-libp2p/core/peer"
	libp2pwebtransport "github.com/libp2p/go-libp2p/p2p/transport/webtransport"
	ma "github.com/multiformats/go-multiaddr"
)

type notifee struct{}

func (notifee) Connected(_ network.Network, c network.Conn) {
	fmt.Printf("CONNECTED %s\n", c.RemotePeer())
}
func (notifee) Disconnected(network.Network, network.Conn) {}
func (notifee) Listen(network.Network, ma.Multiaddr)       {}
func (notifee) ListenClose(network.Network, ma.Multiaddr)  {}

func fail(err error) {
	fmt.Fprintf(os.Stderr, "FAIL %v\n", err)
	os.Exit(1)
}

func main() {
	if len(os.Args) < 2 {
		fail(fmt.Errorf("usage: harness [listen | dial <multiaddr>]"))
	}
	mode := os.Args[1]

	// go-libp2p injects quicreuse.ConnManager via fx when constructing
	// webtransport.New — same path as DefaultTransports.
	opts := []libp2p.Option{
		libp2p.Transport(libp2pwebtransport.New),
		libp2p.DisableRelay(),
	}
	if mode == "listen" {
		opts = append(opts,
			libp2p.ListenAddrStrings("/ip4/0.0.0.0/udp/0/quic-v1/webtransport"))
	}
	h, err := libp2p.New(opts...)
	if err != nil {
		fail(err)
	}
	defer h.Close()

	switch mode {
	case "listen":
		h.Network().Notify(notifee{})
		for _, a := range h.Addrs() {
			fmt.Printf("LISTEN %s/p2p/%s\n", a, h.ID())
		}
		select {} // serve until killed by the test
	case "dial":
		if len(os.Args) < 3 {
			fail(fmt.Errorf("usage: harness dial <multiaddr>"))
		}
		ai, err := peer.AddrInfoFromString(os.Args[2])
		if err != nil {
			fail(err)
		}
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		if err := h.Connect(ctx, *ai); err != nil {
			fail(err)
		}
		fmt.Printf("DIAL_OK %s\n", ai.ID)
	default:
		fail(fmt.Errorf("usage: harness [listen | dial <multiaddr>]"))
	}
}
