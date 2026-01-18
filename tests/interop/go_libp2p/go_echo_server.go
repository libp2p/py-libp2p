package main

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"os/signal"
	"syscall"

	"github.com/libp2p/go-libp2p"
	"github.com/libp2p/go-libp2p/core/network"
	"github.com/libp2p/go-libp2p/core/protocol"
	"github.com/multiformats/go-multiaddr"

	"github.com/libp2p/go-msgio"
)

const EchoProtocol = protocol.ID("/echo/1.0.0")

func main() {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Create a new libp2p host with QUIC transport
	listenAddr, _ := multiaddr.NewMultiaddr("/ip4/0.0.0.0/udp/0/quic-v1")

	host, err := libp2p.New(
		libp2p.ListenAddrs(listenAddr),
		libp2p.DisableRelay(),
	)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Failed to create host: %v\n", err)
		os.Exit(1)
	}
	defer host.Close()

	// Set up echo protocol handler
	host.SetStreamHandler(EchoProtocol, func(s network.Stream) {
		defer s.Close()

		fmt.Fprintf(os.Stderr, "Echo server: Received connection from %s\n", s.Conn().RemotePeer())

		reader := msgio.NewVarintReaderSize(s, 1024*1024) // Max 1MB
		writer := msgio.NewVarintWriter(s)

		for {
			// Read length-prefixed message
			msg, err := reader.ReadMsg()
			if err != nil {
				if err.Error() != "EOF" {
					fmt.Fprintf(os.Stderr, "Echo server: Read error: %v\n", err)
				}
				break
			}

			if len(msg) == 0 {
				fmt.Fprintf(os.Stderr, "Echo server: Empty message, closing\n")
				break
			}

			fmt.Fprintf(os.Stderr, "Echo server: Received (%d bytes): %s\n", len(msg), string(msg))

			// Echo back
			if err := writer.WriteMsg(msg); err != nil {
				fmt.Fprintf(os.Stderr, "Echo server: Write error: %v\n", err)
				break
			}

			fmt.Fprintf(os.Stderr, "Echo server: Echoed message back\n")
			reader.ReleaseMsg(msg)
		}

		fmt.Fprintf(os.Stderr, "Echo server: Connection closed\n")
	})

	// Print connection info (stdout for parsing)
	fmt.Printf("Peer ID: %s\n", host.ID())
	fmt.Println("Listening on:")
	for _, addr := range host.Addrs() {
		fmt.Printf("  %s/p2p/%s\n", addr, host.ID())
	}
	fmt.Printf("Protocol: %s\n", EchoProtocol)
	fmt.Println("Ready for py-libp2p connections!")
	fmt.Println()

	// Flush stdout
	bufio.NewWriter(os.Stdout).Flush()

	// Wait for interrupt
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	select {
	case <-sigCh:
		fmt.Fprintln(os.Stderr, "\nShutdown signal received")
	case <-ctx.Done():
	}
}
