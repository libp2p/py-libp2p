package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/libp2p/go-libp2p"
	"github.com/libp2p/go-libp2p/core/network"
	"github.com/libp2p/go-libp2p/p2p/protocol/circuitv2/relay"
)

type RelayInfo struct {
	PeerID    string   `json:"peer_id"`
	Addresses []string `json:"addresses"`
}

func main() {
	printIDOnly := flag.Bool("print-id-only", false, "Print only peer ID and exit")
	printInfo := flag.Bool("print-info", false, "Print relay info as JSON and exit")
	port := flag.Int("port", 4001, "Port to listen on")
	flag.Parse()

	// Create libp2p host with proper relay support
	h, err := libp2p.New(
		libp2p.ListenAddrStrings(fmt.Sprintf("/ip4/0.0.0.0/tcp/%d", *port)),
		libp2p.EnableRelay(),
	)
	if err != nil {
		log.Fatal(err)
	}
	defer h.Close()

	// Enable circuit relay v2
	_, err = relay.New(h)
	if err != nil {
		log.Fatal("Failed to enable relay:", err)
	}

	if *printIDOnly {
		fmt.Print(h.ID().String())
		return
	}

	if *printInfo {
		addrs := make([]string, len(h.Addrs()))
		for i, addr := range h.Addrs() {
			addrs[i] = addr.String()
		}
		
		info := RelayInfo{
			PeerID:    h.ID().String(),
			Addresses: addrs,
		}
		
		jsonData, err := json.Marshal(info)
		if err != nil {
			log.Fatal(err)
		}
		fmt.Print(string(jsonData))
		return
	}

	log.Printf("Relay server running on: %v", h.Addrs())
	log.Printf("Relay server peer ID: %s", h.ID())

	// Set stream handler for monitoring
	h.SetStreamHandler("/relay/monitor/1.0.0", handleMonitorStream)

	// Log connections
	h.Network().Notify(&network.NotifyBundle{
		ConnectedF: func(n network.Network, conn network.Conn) {
			log.Printf("New connection from peer: %s", conn.RemotePeer())
		},
		DisconnectedF: func(n network.Network, conn network.Conn) {
			log.Printf("Disconnected from peer: %s", conn.RemotePeer())
		},
	})

	// Wait for termination signal
	c := make(chan os.Signal, 1)
	signal.Notify(c, os.Interrupt, syscall.SIGTERM)
	<-c

	log.Println("Shutting down relay server...")
}

func handleMonitorStream(s network.Stream) {
	defer s.Close()
	
	// Send basic status info
	status := map[string]interface{}{
		"status":      "active",
		"timestamp":   time.Now().Unix(),
		"connections": len(s.Conn().RemoteMultiaddr().String()),
	}
	
	data, _ := json.Marshal(status)
	s.Write(data)
}
