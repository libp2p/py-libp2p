// go-mdns-peer.go
// go-libp2p mDNS peer for interop testing with py-libp2p.
//
// Usage:
//   go run go-mdns-peer.go -action <register|discover> -port <port>
//
// Actions:
//   register  - Register an mDNS service and wait for discoveries
//   discover  - Browse for mDNS services and report findings
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"time"

	"github.com/libp2p/go-libp2p"
	"github.com/libp2p/go-libp2p/core/host"
	"github.com/libp2p/go-libp2p/core/peer"
	"github.com/libp2p/go-libp2p/p2p/discovery/mdns"
)

type discoveryNotifee struct {
	host   host.Host
	peers  []peer.AddrInfo
}

func (n *discoveryNotifee) HandlePeerFound(info peer.AddrInfo) {
	if info.ID == n.host.ID() {
		return // skip self
	}
	n.peers = append(n.peers, info)
	fmt.Fprintf(os.Stderr, "[DISCOVERED] Peer: %s\n", info.ID)
	for _, addr := range info.Addrs {
		fmt.Fprintf(os.Stderr, "  Address: %s\n", addr)
	}
}

func main() {
	action := flag.String("action", "register", "Action: register or discover")
	port := flag.Int("port", 4001, "Listen port")
	timeoutSec := flag.Int("timeout", 10, "Timeout in seconds")
	flag.Parse()

	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(*timeoutSec)*time.Second)
	defer cancel()

	h, err := libp2p.New(
		libp2p.ListenAddrStrings(fmt.Sprintf("/ip4/0.0.0.0/tcp/%d", *port)),
		libp2p.NATPortMap(),
	)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Failed to create host: %v\n", err)
		os.Exit(1)
	}
	defer h.Close()

	fmt.Fprintf(os.Stderr, "[HOST] Peer ID: %s\n", h.ID())
	fmt.Fprintf(os.Stderr, "[HOST] Listening on:\n")
	for _, addr := range h.Addrs() {
		fmt.Fprintf(os.Stderr, "  %s/p2p/%s\n", addr, h.ID())
	}

	notifee := &discoveryNotifee{host: h}
	s := mdns.NewMdnsService(h, mdns.ServiceName, notifee)

	if err := s.Start(); err != nil {
		fmt.Fprintf(os.Stderr, "Failed to start mDNS: %v\n", err)
		os.Exit(1)
	}
	defer s.Close()

	switch *action {
	case "register":
		fmt.Fprintf(os.Stderr, "[REGISTER] Service registered, waiting for discoveries...\n")
		<-ctx.Done()
		fmt.Fprintf(os.Stderr, "[TIMEOUT] Total peers discovered: %d\n", len(notifee.peers))

	case "discover":
		fmt.Fprintf(os.Stderr, "[DISCOVER] Browsing for peers...\n")
		<-ctx.Done()
		fmt.Fprintf(os.Stderr, "[TIMEOUT] Total peers discovered: %d\n", len(notifee.peers))

		// Print discovered peers to stdout as JSON-like output
		for _, info := range notifee.peers {
			addrs := make([]string, 0)
			for _, addr := range info.Addrs {
				addrs = append(addrs, addr.String())
			}
			fmt.Printf("PEER|%s|%v\n", info.ID, addrs)
		}

	default:
		fmt.Fprintf(os.Stderr, "Unknown action: %s\n", *action)
		os.Exit(1)
	}
}
