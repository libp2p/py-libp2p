package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"strings"
	"time"

	"github.com/libp2p/go-libp2p"
	"github.com/libp2p/go-libp2p/core/network"
	"github.com/libp2p/go-libp2p/core/peer"
	"github.com/multiformats/go-multiaddr"
)

type ClientInfo struct {
	PeerID           string `json:"peer_id"`
	Addresses        []string `json:"addresses"`
	TargetPeer       string `json:"target_peer,omitempty"`
	ConnectionCount  int    `json:"connection_count"`
	DirectConnection bool   `json:"direct_connection"`
}

func main() {
	printIDOnly := flag.Bool("print-id-only", false, "Print only peer ID and exit")
	printInfo := flag.Bool("print-info", false, "Print client info as JSON and exit")
	relayAddr := flag.String("relay", "", "Relay multiaddr")
	targetPeerID := flag.String("target", "", "Target peer ID")
	duration := flag.Int("duration", 60, "Test duration in seconds")
	flag.Parse()

	// Create libp2p host
	h, err := libp2p.New(
		libp2p.EnableRelay(),
	)
	if err != nil {
		log.Fatal(err)
	}
	defer h.Close()

	if *printIDOnly {
		fmt.Print(h.ID().String())
		return
	}

	log.Printf("Go hole punch client running on: %v", h.Addrs())
	log.Printf("Go hole punch client peer ID: %s", h.ID())

	// Log connection events
	h.Network().Notify(&network.NotifyBundle{
		ConnectedF: func(n network.Network, conn network.Conn) {
			log.Printf("Connected to peer: %s via %s", 
				conn.RemotePeer(), conn.RemoteMultiaddr())
		},
		DisconnectedF: func(n network.Network, conn network.Conn) {
			log.Printf("Disconnected from peer: %s", conn.RemotePeer())
		},
	})

	// Connect to target through relay and attempt connection
	if *relayAddr != "" && *targetPeerID != "" {
		ma, err := multiaddr.NewMultiaddr(*relayAddr)
		if err != nil {
			log.Fatal(err)
		}

		targetID, err := peer.Decode(*targetPeerID)
		if err != nil {
			log.Fatal(err)
		}

		// Create circuit relay address for target
		circuitAddr, err := multiaddr.NewMultiaddr(
			ma.String() + "/p2p-circuit/p2p/" + *targetPeerID)
		if err != nil {
			log.Fatal(err)
		}

		log.Printf("Attempting to connect to target %s through relay...", targetID)

		addrInfo := peer.AddrInfo{
			ID:    targetID,
			Addrs: []multiaddr.Multiaddr{circuitAddr},
		}

		ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
		defer cancel()

		err = h.Connect(ctx, addrInfo)
		if err != nil {
			log.Printf("Failed to connect through relay: %v", err)
		} else {
			log.Printf("Connected to target through relay!")
			
			// Check connection status
			conns := h.Network().ConnsToPeer(targetID)
			for _, conn := range conns {
				log.Printf("Connection to %s: %s", 
					targetID, conn.RemoteMultiaddr())
			}
			
			// Try to open a test stream
			stream, err := h.NewStream(ctx, targetID, "/test/ping/1.0.0")
			if err != nil {
				log.Printf("Failed to open test stream: %v", err)
			} else {
				log.Printf("Successfully opened test stream to target")
				
				// Read response
				buffer := make([]byte, 1024)
				n, err := stream.Read(buffer)
				if err != nil {
					log.Printf("Failed to read from stream: %v", err)
				} else {
					log.Printf("Received response: %s", string(buffer[:n]))
				}
				stream.Close()
			}
		}
	}

	if *printInfo {
		addrs := make([]string, len(h.Addrs()))
		for i, addr := range h.Addrs() {
			addrs[i] = addr.String()
		}
		
		directConn := false
		if *targetPeerID != "" {
			targetID, err := peer.Decode(*targetPeerID)
			if err == nil {
				conns := h.Network().ConnsToPeer(targetID)
				for _, conn := range conns {
					// Check if connection is not through circuit relay
					if !strings.Contains(conn.RemoteMultiaddr().String(), "p2p-circuit") {
						directConn = true
						break
					}
				}
			}
		}
		
		info := ClientInfo{
			PeerID:           h.ID().String(),
			Addresses:        addrs,
			TargetPeer:       *targetPeerID,
			ConnectionCount:  len(h.Network().Conns()),
			DirectConnection: directConn,
		}
		
		jsonData, err := json.Marshal(info)
		if err != nil {
			log.Fatal(err)
		}
		fmt.Print(string(jsonData))
		return
	}

	// Keep running for the specified duration
	time.Sleep(time.Duration(*duration) * time.Second)
	log.Println("Client test completed")
}
