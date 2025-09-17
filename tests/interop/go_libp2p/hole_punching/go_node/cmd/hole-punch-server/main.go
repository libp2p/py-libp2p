package main

import (
    "context"
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
    "github.com/libp2p/go-libp2p/core/peer"
    "github.com/multiformats/go-multiaddr"
)

type ServerInfo struct {
    PeerID      string   `json:"peer_id"`
    Addresses   []string `json:"addresses"`
    Status      string   `json:"status"`
    Connections int      `json:"connections"`
}

func main() {
    printIDOnly := flag.Bool("print-id-only", false, "Print only peer ID and exit")
    printInfo := flag.Bool("print-info", false, "Print server info as JSON and exit")
    relayAddr := flag.String("relay", "", "Relay multiaddr to connect to")
    port := flag.Int("port", 0, "Port to listen on (0 for random)")
    duration := flag.Int("duration", 120, "Server duration in seconds") // ADD THIS LINE
    flag.Parse()

    // Create libp2p host options
    opts := []libp2p.Option{
        libp2p.EnableRelay(),
    }

    if *port > 0 {
        opts = append(opts, libp2p.ListenAddrStrings(fmt.Sprintf("/ip4/0.0.0.0/tcp/%d", *port)))
    }

    // Create libp2p host
    h, err := libp2p.New(opts...)
    if err != nil {
        log.Fatal(err)
    }
    defer h.Close()

    if *printIDOnly {
        fmt.Print(h.ID().String())
        return
    }

    if *printInfo {
        addrs := make([]string, len(h.Addrs()))
        for i, addr := range h.Addrs() {
            addrs[i] = addr.String()
        }
        
        info := ServerInfo{
            PeerID:      h.ID().String(),
            Addresses:   addrs,
            Status:      "active",
            Connections: len(h.Network().Conns()),
        }
        
        jsonData, err := json.Marshal(info)
        if err != nil {
            log.Fatal(err)
        }
        fmt.Print(string(jsonData))
        return
    }

    log.Printf("Go hole punch server running on: %v", h.Addrs())
    log.Printf("Go hole punch server peer ID: %s", h.ID())

    // Connect to relay if provided
    if *relayAddr != "" {
        ma, err := multiaddr.NewMultiaddr(*relayAddr)
        if err != nil {
            log.Fatal(err)
        }

        addrInfo, err := peer.AddrInfoFromP2pAddr(ma)
        if err != nil {
            log.Fatal(err)
        }

        ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
        defer cancel()

        err = h.Connect(ctx, *addrInfo)
        if err != nil {
            log.Printf("Warning: Failed to connect to relay: %v", err)
        } else {
            log.Printf("Connected to relay: %s", addrInfo.ID)
        }
    }

    // Set up stream handler for testing
    h.SetStreamHandler("/test/ping/1.0.0", handlePingStream)

    // Log connection events
    h.Network().Notify(&network.NotifyBundle{
        ConnectedF: func(n network.Network, conn network.Conn) {
            log.Printf("New connection from peer: %s via %s", 
                conn.RemotePeer(), conn.RemoteMultiaddr())
        },
        DisconnectedF: func(n network.Network, conn network.Conn) {
            log.Printf("Disconnected from peer: %s", conn.RemotePeer())
        },
    })

    // Wait for termination signal
    c := make(chan os.Signal, 1)
    signal.Notify(c, os.Interrupt, syscall.SIGTERM)

    // Run for specified duration or until signal
    select {
    case <-c:
        log.Println("Received shutdown signal")
    case <-time.After(time.Duration(*duration) * time.Second): // USE THE DURATION FLAG
        log.Println("Test duration completed")
    }

    log.Println("Shutting down hole punch server...")
}

func handlePingStream(s network.Stream) {
    defer s.Close()
    log.Printf("Received ping stream from: %s", s.Conn().RemotePeer())
    
    // Echo back a simple response
    response := map[string]interface{}{
        "status":    "pong",
        "timestamp": time.Now().Unix(),
        "peer_id":   s.Conn().LocalPeer().String(),
    }
    
    data, _ := json.Marshal(response)
    s.Write(data)
}
