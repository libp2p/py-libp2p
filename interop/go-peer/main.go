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
		[]multiaddr.Multiaddr{h.Addrs()[0]},
		ds,
	)
	if err != nil {
		panic(err)
	}

	fmt.Println("New ipfslite...")
	lite, err := ipfslite.New(ctx, ds, nil, h, dht, nil)
	if err != nil {
		panic(err)
	}

	if targetAddr != "none" {
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
	} else {
	    fmt.Println("ADDR=" + fmt.Sprintf("%s/p2p/%s", h.Addrs()[0], h.ID()))
	}

	if command == "add" {
		text := os.Args[3]
		reader := bytes.NewReader([]byte(text))
		node, err := lite.AddFile(ctx, reader, &ipfslite.AddParams{RawLeaves: true})
		if err != nil {
			panic(err)
		}
		fmt.Println("CID=" + node.Cid().String())
		time.Sleep(10 * time.Second)
	} else if command == "add-file" {
		filePath := os.Args[3]
		file, err := os.Open(filePath)
		if err != nil {
			panic(err)
		}
		defer file.Close()
		node, err := lite.AddFile(ctx, file, &ipfslite.AddParams{RawLeaves: true})
		if err != nil {
			panic(err)
		}
		fmt.Println("CID=" + node.Cid().String())
		time.Sleep(180 * time.Second)
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
	} else if command == "fetch-file" {
		c, err := cid.Decode(os.Args[3])
		if err != nil {
			panic(err)
		}
		outPath := os.Args[4]
		reader, err := lite.GetFile(ctx, c)
		if err != nil {
			panic(err)
		}
		outFile, err := os.Create(outPath)
		if err != nil {
			panic(err)
		}
		defer outFile.Close()
		_, err = io.Copy(outFile, reader)
		if err != nil {
			panic(err)
		}
		fmt.Println("DONE_FETCH_FILE")
	}
}
