package main

import (
	"context"
	"crypto/rand"
	"flag"
	"fmt"
	"io"
	"log"
	"os"
	"time"

	"github.com/go-redis/redis/v8"
	"github.com/libp2p/go-libp2p"
	"github.com/libp2p/go-libp2p/core/host"
	"github.com/libp2p/go-libp2p/core/network"
	"github.com/libp2p/go-libp2p/core/peer"
	"github.com/libp2p/go-libp2p/core/protocol"
	libp2pwebrtc "github.com/libp2p/go-libp2p/p2p/transport/webrtc"
	"github.com/multiformats/go-multiaddr"
)

const (
	PingProtocol          = "/ipfs/ping/1.0.0"
	CoordinationKeyPrefix = "interop:webrtc"
)

type GoPeer struct {
	role       string
	host       host.Host
	redis      *redis.Client
	ctx        context.Context
	listenPort int
}

func NewGoPeer(role string, redisClient *redis.Client, listenPort int) *GoPeer {
	return &GoPeer{
		role:       role,
		redis:      redisClient,
		ctx:        context.Background(),
		listenPort: listenPort,
	}
}

func (p *GoPeer) SetupHost() error {
	stunServer := os.Getenv("STUN_SERVER")
	if stunServer == "" {
		stunServer = "stun:stun.l.google.com:19302"
	}
	log.Printf("Using STUN server: %s", stunServer)

	listenAddr := fmt.Sprintf("/ip4/0.0.0.0/udp/%d/webrtc-direct", p.listenPort)

	h, err := libp2p.New(
		libp2p.Transport(libp2pwebrtc.New),
		libp2p.ListenAddrStrings(listenAddr),
		libp2p.EnableRelay(),
	)
	if err != nil {
		return fmt.Errorf("failed to create host: %w", err)
	}

	p.host = h
	log.Printf("Peer ID: %s", h.ID())
	log.Printf("Listening addresses: %v", h.Addrs())

	return nil
}

func (p *GoPeer) StartListener() error {
	p.host.SetStreamHandler(protocol.ID(PingProtocol), p.pingHandler)

	addrs := p.host.Addrs()
	if len(addrs) == 0 {
		return fmt.Errorf("no listening addresses")
	}

	addrWithPeer := fmt.Sprintf("%s/p2p/%s", addrs, p.host.ID())
	if err := p.redis.Set(p.ctx, CoordinationKeyPrefix+":listener:addr", addrWithPeer, 5*time.Minute).Err(); err != nil {
		return fmt.Errorf("failed to publish address: %w", err)
	}

	if err := p.redis.Set(p.ctx, CoordinationKeyPrefix+":listener:ready", "1", 5*time.Minute).Err(); err != nil {
		return fmt.Errorf("failed to signal ready: %w", err)
	}

	log.Println("Listener ready")
	select {}
}

func (p *GoPeer) pingHandler(stream network.Stream) {
	defer stream.Close()

	buf := make([]byte, 32)
	n, err := io.ReadFull(stream, buf)
	if err != nil {
		log.Printf("error reading ping: %v", err)
		return
	}
	log.Printf("received %d bytes", n)

	if _, err := stream.Write(buf); err != nil {
		log.Printf("error writing pong: %v", err)
		return
	}
}

func (p *GoPeer) StartDialer() error {
	timeout := time.After(60 * time.Second)
	ticker := time.NewTicker(1 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-timeout:
			return fmt.Errorf("timeout waiting for listener")
		case <-ticker.C:
			ready, err := p.redis.Get(p.ctx, CoordinationKeyPrefix+":listener:ready").Result()
			if err == nil && ready == "1" {
				goto ListenerReady
			}
		}
	}

ListenerReady:
	listenerAddrStr, err := p.redis.Get(p.ctx, CoordinationKeyPrefix+":listener:addr").Result()
	if err != nil {
		return fmt.Errorf("failed to get listener address: %w", err)
	}

	listenerAddr, err := multiaddr.NewMultiaddr(listenerAddrStr)
	if err != nil {
		return fmt.Errorf("failed to parse listener address: %w", err)
	}

	peerInfo, err := peer.AddrInfoFromP2pAddr(listenerAddr)
	if err != nil {
		return fmt.Errorf("failed to get peer info: %w", err)
	}

	p.host.Peerstore().AddAddrs(peerInfo.ID, peerInfo.Addrs, time.Hour)

	if err := p.host.Connect(p.ctx, *peerInfo); err != nil {
		log.Printf("dial failed: %v", err)
		p.redis.Set(p.ctx, CoordinationKeyPrefix+":connection:status", fmt.Sprintf("failed:%v", err), 5*time.Minute)
		return err
	}

	p.redis.Set(p.ctx, CoordinationKeyPrefix+":connection:status", "connected", 5*time.Minute)
	return p.testPing(peerInfo.ID)
}

func (p *GoPeer) testPing(peerID peer.ID) error {
	stream, err := p.host.NewStream(p.ctx, peerID, protocol.ID(PingProtocol))
	if err != nil {
		p.redis.Set(p.ctx, CoordinationKeyPrefix+":ping:status", fmt.Sprintf("failed:%v", err), 5*time.Minute)
		return fmt.Errorf("failed to open stream: %w", err)
	}
	defer stream.Close()

	pingPayload := make([]byte, 32)
	if _, err := rand.Read(pingPayload); err != nil {
		p.redis.Set(p.ctx, CoordinationKeyPrefix+":ping:status", fmt.Sprintf("failed:%v", err), 5*time.Minute)
		return fmt.Errorf("failed to generate payload: %w", err)
	}

	if _, err := stream.Write(pingPayload); err != nil {
		p.redis.Set(p.ctx, CoordinationKeyPrefix+":ping:status", fmt.Sprintf("failed:%v", err), 5*time.Minute)
		return fmt.Errorf("failed to write ping: %w", err)
	}

	pongPayload := make([]byte, 32)
	if _, err := io.ReadFull(stream, pongPayload); err != nil {
		p.redis.Set(p.ctx, CoordinationKeyPrefix+":ping:status", fmt.Sprintf("failed:%v", err), 5*time.Minute)
		return fmt.Errorf("failed to read pong: %w", err)
	}

	match := true
	for i := range pingPayload {
		if pingPayload[i] != pongPayload[i] {
			match = false
			break
		}
	}

	if match {
		p.redis.Set(p.ctx, CoordinationKeyPrefix+":ping:status", "passed", 5*time.Minute)
	} else {
		p.redis.Set(p.ctx, CoordinationKeyPrefix+":ping:status", "failed:mismatch", 5*time.Minute)
		return fmt.Errorf("ping payload mismatch")
	}

	return nil
}

func (p *GoPeer) Run() error {
	if err := p.SetupHost(); err != nil {
		return err
	}

	if p.role == "listener" {
		return p.StartListener()
	} else if p.role == "dialer" {
		return p.StartDialer()
	}

	return fmt.Errorf("invalid role: %s", p.role)
}

func main() {
	roleFlag := flag.String("role", "", "Peer role (listener or dialer)")
	portFlag := flag.Int("port", 9091, "Listen port for WebRTC")
	redisHostFlag := flag.String("redis-host", "localhost", "Redis host")
	redisPortFlag := flag.Int("redis-port", 6379, "Redis port")
	flag.Parse()

	if *roleFlag != "listener" && *roleFlag != "dialer" {
		log.Fatal("invalid role: must be 'listener' or 'dialer'")
	}

	redisAddr := fmt.Sprintf("%s:%d", *redisHostFlag, *redisPortFlag)
	log.Printf("Connecting to Redis at %s", redisAddr)

	redisClient := redis.NewClient(&redis.Options{
		Addr: redisAddr,
	})

	ctx := context.Background()
	if _, err := redisClient.Ping(ctx).Result(); err != nil {
		log.Fatalf("failed to connect to Redis: %v", err)
	}

	peer := NewGoPeer(*roleFlag, redisClient, *portFlag)
	if err := peer.Run(); err != nil {
		log.Fatalf("fatal error: %v", err)
	}
}
