package main

import (
	"bufio"
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/libp2p/go-libp2p"
	pubsub "github.com/libp2p/go-libp2p-pubsub"
	"github.com/libp2p/go-libp2p/core/host"
	"github.com/libp2p/go-libp2p/core/peer"
	"github.com/libp2p/go-libp2p/core/peerstore"
	"github.com/libp2p/go-libp2p/p2p/muxer/yamux"
	"github.com/libp2p/go-libp2p/p2p/security/noise"
	"github.com/multiformats/go-multiaddr"
)

type GoLibp2pNode struct {
	host   host.Host
	pubsub *pubsub.PubSub
	topics map[string]*pubsub.Topic
	subs   map[string]*pubsub.Subscription
	ctx    context.Context
	cancel context.CancelFunc
	mu     sync.RWMutex
}

func NewGoLibp2pNode(listenAddr string) (*GoLibp2pNode, error) {
	ctx, cancel := context.WithCancel(context.Background())

	// FIXED: Clean configuration without problematic GossipSubParams
	h, err := libp2p.New(
		libp2p.ListenAddrStrings(listenAddr),
		libp2p.Ping(false),
		// Explicitly configure security protocols
		libp2p.Security(noise.ID, noise.New),
		// Explicitly configure yamux
		libp2p.Muxer(yamux.ID, yamux.DefaultTransport),
		// Disable problematic features
		libp2p.DisableRelay(),
	)
	if err != nil {
		cancel()
		return nil, fmt.Errorf("failed to create host: %w", err)
	}

	// FIXED: Use default GossipSub configuration - DO NOT customize parameters
	// The custom GossipSubParams was causing divide by zero errors
	ps, err := pubsub.NewGossipSub(ctx, h,
		pubsub.WithMessageSigning(true),
		pubsub.WithStrictSignatureVerification(true),
		pubsub.WithFloodPublish(true),
		pubsub.WithPeerExchange(true),
		// REMOVED: Custom GossipSubParams that were causing the panic
		// The default parameters work fine for interoperability
	)
	if err != nil {
		h.Close()
		cancel()
		return nil, fmt.Errorf("failed to create pubsub: %w", err)
	}

	node := &GoLibp2pNode{
		host:   h,
		pubsub: ps,
		topics: make(map[string]*pubsub.Topic),
		subs:   make(map[string]*pubsub.Subscription),
		ctx:    ctx,
		cancel: cancel,
	}

	// Log configuration details
	protocols := h.Mux().Protocols()
	log.Printf("Go node available protocols: %v", protocols)

	return node, nil
}

func (n *GoLibp2pNode) GetAddresses() []string {
	var addrs []string
	for _, addr := range n.host.Addrs() {
		addrs = append(addrs, fmt.Sprintf("%s/p2p/%s", addr, n.host.ID().String()))
	}
	return addrs
}

func (n *GoLibp2pNode) GetPeerID() string {
	return n.host.ID().String()
}

func (n *GoLibp2pNode) ConnectToPeer(peerAddr string) error {
	maddr, err := multiaddr.NewMultiaddr(peerAddr)
	if err != nil {
		return fmt.Errorf("invalid multiaddr %s: %w", peerAddr, err)
	}

	info, err := peer.AddrInfoFromP2pAddr(maddr)
	if err != nil {
		return fmt.Errorf("failed to get peer info from %s: %w", peerAddr, err)
	}

	log.Printf("Attempting to connect to peer: %s at %v", info.ID, info.Addrs)

	if err := n.host.Connect(n.ctx, *info); err != nil {
		return fmt.Errorf("failed to connect to peer %s: %w", info.ID, err)
	}

	n.host.Peerstore().AddAddrs(info.ID, info.Addrs, peerstore.PermanentAddrTTL)
	log.Printf("Successfully connected to peer: %s", info.ID)

	// Give connection time to stabilize
	time.Sleep(2 * time.Second)
	return nil
}

func (n *GoLibp2pNode) Subscribe(topicName string) error {
	n.mu.Lock()
	defer n.mu.Unlock()

	if _, exists := n.subs[topicName]; exists {
		return fmt.Errorf("already subscribed to topic: %s", topicName)
	}

	topic, err := n.pubsub.Join(topicName)
	if err != nil {
		return fmt.Errorf("failed to join topic %s: %w", topicName, err)
	}

	sub, err := topic.Subscribe()
	if err != nil {
		topic.Close()
		return fmt.Errorf("failed to subscribe to topic %s: %w", topicName, err)
	}

	n.topics[topicName] = topic
	n.subs[topicName] = sub

	go n.handleMessages(topicName, sub)
	log.Printf("Successfully subscribed to topic: %s", topicName)
	return nil
}

func (n *GoLibp2pNode) Publish(topicName, message string) error {
	n.mu.RLock()
	topic, exists := n.topics[topicName]
	n.mu.RUnlock()

	if !exists {
		return fmt.Errorf("not subscribed to topic: %s", topicName)
	}

	if err := topic.Publish(n.ctx, []byte(message)); err != nil {
		return fmt.Errorf("failed to publish to topic %s: %w", topicName, err)
	}

	log.Printf("Published message to %s: %s", topicName, message)
	return nil
}

func (n *GoLibp2pNode) handleMessages(topicName string, sub *pubsub.Subscription) {
	for {
		msg, err := sub.Next(n.ctx)
		if err != nil {
			log.Printf("Error reading from subscription %s: %v", topicName, err)
			return
		}

		if msg.ReceivedFrom == n.host.ID() {
			continue
		}

		log.Printf("Received message on %s from %s: %s", topicName, msg.ReceivedFrom, string(msg.Data))
	}
}

func (n *GoLibp2pNode) GetConnectedPeers() []string {
	var peers []string
	for _, peerID := range n.host.Network().Peers() {
		peers = append(peers, peerID.String())
	}
	return peers
}

func (n *GoLibp2pNode) GetMeshPeers(topicName string) []string {
	n.mu.RLock()
	defer n.mu.RUnlock()

	var meshPeers []string
	peers := n.pubsub.ListPeers(topicName)
	for _, peer := range peers {
		meshPeers = append(meshPeers, peer.String())
	}
	return meshPeers
}

func (n *GoLibp2pNode) Close() error {
	n.cancel()
	return n.host.Close()
}

func main() {
	var listenAddr = flag.String("listen", "/ip4/127.0.0.1/tcp/0", "Listen address")
	var connectAddr = flag.String("connect", "", "Peer address to connect to")
	var topic = flag.String("topic", "interop-test", "Topic name")
	var mode = flag.String("mode", "interactive", "Mode: interactive, publisher, subscriber, or test")
	var message = flag.String("message", "Hello from Go!", "Message to publish")
	var count = flag.Int("count", 5, "Number of messages to send in test mode")
	flag.Parse()

	node, err := NewGoLibp2pNode(*listenAddr)
	if err != nil {
		log.Fatalf("Failed to create node: %v", err)
	}
	defer node.Close()

	log.Printf("Go-libp2p node started successfully")
	log.Printf("Peer ID: %s", node.GetPeerID())
	for _, addr := range node.GetAddresses() {
		log.Printf("Listening on: %s", addr)
	}

	if *connectAddr != "" {
		if err := node.ConnectToPeer(*connectAddr); err != nil {
			log.Fatalf("Failed to connect to peer: %v", err)
		}
	}

	if err := node.Subscribe(*topic); err != nil {
		log.Fatalf("Failed to subscribe to topic: %v", err)
	}

	// Wait for gossipsub mesh to form
	log.Printf("Waiting for gossipsub mesh formation...")
	time.Sleep(3 * time.Second)

	switch *mode {
	case "interactive":
		runInteractiveMode(node, *topic)
	case "publisher":
		runPublisherMode(node, *topic, *message, *count)
	case "subscriber":
		runSubscriberMode()
	case "test":
		runTestMode(node, *topic, *message, *count)
	default:
		log.Fatalf("Unknown mode: %s", *mode)
	}
}

func runInteractiveMode(node *GoLibp2pNode, topic string) {
	log.Println("Interactive mode. Type messages to publish, 'quit' to exit:")
	scanner := bufio.NewScanner(os.Stdin)

	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "quit" {
			break
		}
		if line != "" {
			if err := node.Publish(topic, line); err != nil {
				log.Printf("Failed to publish: %v", err)
			}
		}
	}
}

func runPublisherMode(node *GoLibp2pNode, topic, message string, count int) {
	log.Printf("Publisher mode: sending %d messages", count)

	for i := 1; i <= count; i++ {
		msg := fmt.Sprintf("%s #%d", message, i)
		if err := node.Publish(topic, msg); err != nil {
			log.Printf("Failed to publish message %d: %v", i, err)
		}
		time.Sleep(time.Second)
	}

	log.Println("Publishing complete")
	time.Sleep(5 * time.Second)
}

func runSubscriberMode() {
	log.Println("Subscriber mode: waiting for messages...")
	log.Println("Press Ctrl+C to stop")

	c := make(chan os.Signal, 1)
	signal.Notify(c, os.Interrupt, syscall.SIGTERM)
	<-c
	log.Println("Received interrupt signal, shutting down...")
}

func runTestMode(node *GoLibp2pNode, topic, message string, count int) {
	log.Printf("Test mode: mesh peers before publishing: %v", node.GetMeshPeers(topic))

	go func() {
		time.Sleep(2 * time.Second)
		for i := 1; i <= count; i++ {
			msg := fmt.Sprintf("%s-test-%d-%d", message, os.Getpid(), i)
			if err := node.Publish(topic, msg); err != nil {
				log.Printf("Failed to publish test message %d: %v", i, err)
			}
			time.Sleep(500 * time.Millisecond)
		}
	}()

	timeout := time.After(20 * time.Second)
	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-timeout:
			log.Println("Test complete - timeout reached")
			log.Printf("Final - Connected peers: %v", node.GetConnectedPeers())
			log.Printf("Final - Mesh peers for topic: %v", node.GetMeshPeers(topic))
			return
		case <-ticker.C:
			connectedPeers := node.GetConnectedPeers()
			meshPeers := node.GetMeshPeers(topic)
			log.Printf("Status - Connected: %d, Mesh peers: %d", len(connectedPeers), len(meshPeers))
		}
	}
}
