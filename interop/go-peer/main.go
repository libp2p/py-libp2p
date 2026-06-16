package main

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"os"
	"time"

	ipfslite "github.com/hsanjuan/ipfs-lite"
	"github.com/ipfs/go-cid"
	"github.com/ipfs/go-datastore"
	"github.com/ipfs/go-datastore/sync"
	logging "github.com/ipfs/go-log/v2"
	"github.com/libp2p/go-libp2p"
	crypto "github.com/libp2p/go-libp2p/core/crypto"
	"github.com/libp2p/go-libp2p/core/peer"
	"github.com/multiformats/go-multiaddr"
)

func main() {
	logging.SetLogLevel("*", "debug")

	if len(os.Args) < 4 {
		fmt.Println("Usage: go-peer <multiaddr> [fetch <cid> | add <text>]")
		os.Exit(1)
	}

	targetAddr := os.Args[1]
	command := os.Args[2]

	ctx := context.Background()
	priv, _, err := crypto.GenerateKeyPair(crypto.Ed25519, 256)
	if err != nil {
		panic(err)
	}

	h, err := libp2p.New(
		libp2p.ListenAddrStrings("/ip4/127.0.0.1/tcp/0"),
		libp2p.Identity(priv),
	)
	if err != nil {
		panic(err)
	}

	ds := sync.MutexWrap(datastore.NewMapDatastore())

	fmt.Println("SetupLibp2p...")
	h, dht, err := ipfslite.SetupLibp2p(
		ctx,
		priv,
		nil,
		[]multiaddr.Multiaddr{},
		ds,
		libp2p.NoListenAddrs,
	)
	if err != nil {
		panic(err)
	}

	fmt.Println("New ipfslite...")
	lite, err := ipfslite.New(ctx, ds, nil, h, dht, nil)
	if err != nil {
		panic(err)
	}

	fmt.Println("Parsing multiaddr...")
	maddr, err := multiaddr.NewMultiaddr(targetAddr)
	if err != nil {
		panic(err)
	}

	peerInfo, err := peer.AddrInfoFromP2pAddr(maddr)
	if err != nil {
		panic(err)
	}

	fmt.Println("Connecting...")
	err = h.Connect(ctx, *peerInfo)
	if err != nil {
		panic(err)
	}

	fmt.Println("Connected. Executing command...")
	if command == "add" {
		text := os.Args[3]
		reader := bytes.NewReader([]byte(text))
		node, err := lite.AddFile(ctx, reader, nil)
		if err != nil {
			panic(err)
		}
		fmt.Println("DONE_ADD:", node.Cid().String())
		time.Sleep(10 * time.Second)
	} else if command == "fetch" {
		c, err := cid.Decode(os.Args[3])
		if err != nil {
			panic(err)
		}
		reader, err := lite.GetFile(ctx, c)
		if err != nil {
			panic(err)
		}
		content, err := io.ReadAll(reader)
		if err != nil {
			panic(err)
		}
		fmt.Println("DONE_FETCH:", string(content))
	}
}
