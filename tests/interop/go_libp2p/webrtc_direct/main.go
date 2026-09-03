// Minimal go-libp2p WebRTC-Direct interop harness for py-libp2p's test suite.
//
// Modes:
//
//	./harness listen                 — listen on an OS-chosen UDP port, print
//	                                   "LISTEN <multiaddr-with-/p2p/>" once per
//	                                   address, then "CONNECTED <peer>" for each
//	                                   secured inbound connection.
//	./harness dial -version N <addr> — dial a /webrtc-direct multiaddr speaking
//	                                   WebRTC-Direct vN (1 or 2), print
//	                                   "DIAL_OK <peer>" and exit 0.
//
// The listener accepts v1 and v2 regardless of -version.
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"time"

	"github.com/libp2p/go-libp2p"
	"github.com/libp2p/go-libp2p/core/network"
	"github.com/libp2p/go-libp2p/core/peer"
	libp2pwebrtc "github.com/libp2p/go-libp2p/p2p/transport/webrtc"
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
	// Subcommand-style CLI: mode is argv[1], flags follow it.
	//   harness listen
	//   harness dial -version N <multiaddr>
	if len(os.Args) < 2 {
		fail(fmt.Errorf("usage: harness [listen | dial -version N <multiaddr>]"))
	}
	mode := os.Args[1]
	fs := flag.NewFlagSet(mode, flag.ExitOnError)
	version := fs.Int("version", 1, "WebRTC-Direct dial version (1 or 2)")
	_ = fs.Parse(os.Args[2:])

	opts := []libp2p.Option{
		libp2p.Transport(libp2pwebrtc.New, libp2pwebrtc.WithDialerVersion(*version)),
		libp2p.DisableRelay(),
	}
	if mode == "listen" {
		opts = append(opts,
			libp2p.ListenAddrStrings("/ip4/0.0.0.0/udp/0/webrtc-direct"))
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
		ai, err := peer.AddrInfoFromString(fs.Arg(0))
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
		fail(fmt.Errorf("usage: harness [listen | dial -version N <multiaddr>]"))
	}
}
