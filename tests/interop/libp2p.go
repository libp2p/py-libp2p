package main

import (
	"context"
	// "crypto/rand"
	"fmt"
	mrand "math/rand"

	libp2p "github.com/libp2p/go-libp2p"
	"github.com/libp2p/go-libp2p-core/crypto"

	// "github.com/libp2p/go-libp2p-core/crypto"
	golog "github.com/ipfs/go-log"
	gologging "github.com/whyrusleeping/go-logging"
	// golog "github.com/ipfs/go-log"
	// gologging "github.com/whyrusleeping/go-logging"
)

func main() {
	// priv, _, err := crypto.GenerateEd25519Key(nil)
	r := mrand.New(mrand.NewSource(int64(0)))
	golog.SetAllLoggers(gologging.DEBUG) // Change to DEBUG for extra info

	// Generate a key pair for this host. We will use it at least
	// to obtain a valid host ID.
	priv, _, err := crypto.GenerateKeyPairWithReader(crypto.ECDSA, 0, r)
	if err != nil {
		panic(err)
	}
	// if err != nil {
	// 	panic(err)
	// }
	// The context governs the lifetime of the libp2p node
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// To construct a simple host with all the default settings, just use `New`
	h, err := libp2p.New(
		ctx,
		libp2p.Identity(priv),
		libp2p.ListenAddrStrings("/ip4/0.0.0.0/tcp/8000"),
		libp2p.NoSecurity,
	)
	if err != nil {
		panic(err)
	}

	fmt.Printf("Hello World, my hosts ID is %s\n", h.ID())
	fmt.Println(h.ID(), h.Addrs())

	select {}
}
