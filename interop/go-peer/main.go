package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"time"

	ipfslite "github.com/hsanjuan/ipfs-lite"
	"github.com/ipfs/go-cid"
	"github.com/ipfs/go-datastore"
	"github.com/ipfs/go-datastore/sync"
	format "github.com/ipfs/go-ipld-format"
	logging "github.com/ipfs/go-log/v2"
	"github.com/libp2p/go-libp2p"
	crypto "github.com/libp2p/go-libp2p/core/crypto"
	"github.com/libp2p/go-libp2p/core/peer"
	"github.com/multiformats/go-multiaddr"
)

func main() {
	logging.SetLogLevel("*", "debug")

	if len(os.Args) < 3 {
		fmt.Println("Usage: go-peer <multiaddr|none> <command> [args...]")
		fmt.Println("Commands:")
		fmt.Println("  add <text>              - Add text as a file")
		fmt.Println("  add-file <path>         - Add a file")
		fmt.Println("  fetch <cid>             - Fetch text content")
		fmt.Println("  fetch-file <cid> <out>  - Fetch file to disk")
		fmt.Println("  add-node <json>         - Add a DAG-JSON node")
		fmt.Println("  get-node <cid>          - Get a DAG node")
		fmt.Println("  remove <cid>            - Remove a block locally")
		fmt.Println("  has-block <cid>         - Check if block exists")
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
		fmt.Println("Connected. Bootstrapping DHT...")
		lite.Bootstrap([]peer.AddrInfo{*peerInfo})
		fmt.Println("DHT Bootstrap started. Executing command...")
	} else {
		fmt.Println("ADDR=" + fmt.Sprintf("%s/p2p/%s", h.Addrs()[0], h.ID()))
	}

	switch command {
	case "add":
		text := os.Args[3]
		reader := bytes.NewReader([]byte(text))
		node, err := lite.AddFile(ctx, reader, &ipfslite.AddParams{RawLeaves: true})
		if err != nil {
			panic(err)
		}
		fmt.Println("CID=" + node.Cid().String())
		time.Sleep(10 * time.Second)

	case "add-file":
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

	case "fetch":
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

	case "fetch-file":
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

	case "has-block":
		c, err := cid.Decode(os.Args[3])
		if err != nil {
			panic(err)
		}
		has, err := lite.HasBlock(ctx, c)
		if err != nil {
			fmt.Printf("HAS_BLOCK=error:%s\n", err)
		} else {
			fmt.Printf("HAS_BLOCK=%v\n", has)
		}

	case "remove":
		c, err := cid.Decode(os.Args[3])
		if err != nil {
			panic(err)
		}
		err = lite.Remove(ctx, c)
		if err != nil {
			fmt.Printf("REMOVE=error:%s\n", err)
		} else {
			fmt.Println("REMOVE=ok")
		}

	case "add-node":
		// Add a raw DAG node (just store arbitrary bytes via Add)
		jsonStr := os.Args[3]
		reader := bytes.NewReader([]byte(jsonStr))
		node, err := lite.AddFile(ctx, reader, &ipfslite.AddParams{RawLeaves: true})
		if err != nil {
			panic(err)
		}
		fmt.Println("CID=" + node.Cid().String())
		time.Sleep(60 * time.Second)

	case "get-node":
		c, err := cid.Decode(os.Args[3])
		if err != nil {
			panic(err)
		}
		node, err := lite.Get(ctx, c)
		if err != nil {
			panic(err)
		}
		rawData := node.RawData()
		fmt.Println("NODE_SIZE=" + fmt.Sprintf("%d", len(rawData)))
		// Try to print as string if it looks like text
		fmt.Println("NODE_DATA=" + string(rawData))
		fmt.Println("NODE_CID=" + node.Cid().String())
		// Print links
		links := node.Links()
		if len(links) > 0 {
			linkData := make([]map[string]interface{}, len(links))
			for i, l := range links {
				linkData[i] = map[string]interface{}{
					"name": l.Name,
					"size": l.Size,
					"cid":  l.Cid.String(),
				}
			}
			jsonBytes, _ := json.Marshal(linkData)
			fmt.Println("NODE_LINKS=" + string(jsonBytes))
		} else {
			fmt.Println("NODE_LINKS=[]")
		}

	case "add-get-remove":
		// Compound test: add, verify has, remove, verify gone
		text := os.Args[3]
		reader := bytes.NewReader([]byte(text))
		node, err := lite.AddFile(ctx, reader, &ipfslite.AddParams{RawLeaves: true})
		if err != nil {
			panic(err)
		}
		addedCid := node.Cid()
		fmt.Println("ADDED_CID=" + addedCid.String())

		// Verify has
		has, _ := lite.HasBlock(ctx, addedCid)
		fmt.Printf("HAS_AFTER_ADD=%v\n", has)

		// Remove
		err = lite.Remove(ctx, addedCid)
		if err != nil {
			fmt.Printf("REMOVE_ERR=%s\n", err)
		}

		// Verify gone
		_, err = lite.Get(ctx, addedCid)
		if err != nil {
			fmt.Println("GONE_AFTER_REMOVE=true")
		} else {
			fmt.Println("GONE_AFTER_REMOVE=false")
		}

	case "blockstore-roundtrip":
		// Test: add file, check has, fetch, compare sizes
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
		rootCid := node.Cid()
		fmt.Println("CID=" + rootCid.String())

		// HasBlock
		has, _ := lite.HasBlock(ctx, rootCid)
		fmt.Printf("HAS_BLOCK=%v\n", has)

		// GetFile and report size
		reader, err := lite.GetFile(ctx, rootCid)
		if err != nil {
			panic(err)
		}
		content, _ := io.ReadAll(reader)
		fmt.Printf("CONTENT_SIZE=%d\n", len(content))

		// Count DAG nodes by walking
		nodeCount := 0
		var walk func(format.Node)
		walk = func(n format.Node) {
			nodeCount++
			for _, l := range n.Links() {
				child, err := lite.Get(ctx, l.Cid)
				if err == nil {
					walk(child)
				}
			}
		}
		walk(node)
		fmt.Printf("DAG_NODE_COUNT=%d\n", nodeCount)

	default:
		fmt.Printf("Unknown command: %s\n", command)
		os.Exit(1)
	}
}
