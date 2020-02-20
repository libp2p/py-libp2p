package utils

import (
	"context"
	"crypto/rand"
	"fmt"
	"io"
	"log"
	mrand "math/rand"

	"github.com/libp2p/go-libp2p"
	"github.com/libp2p/go-libp2p-core/crypto"
	"github.com/libp2p/go-libp2p-core/host"
	plaintext "github.com/libp2p/go-libp2p-core/sec/insecure"
	noise "github.com/libp2p/go-libp2p-noise"
	secio "github.com/libp2p/go-libp2p-secio"

	ma "github.com/multiformats/go-multiaddr"
)

// MakeBasicHost creates a LibP2P host with a random peer ID listening on the
// given multiaddress. It won't encrypt the connection if insecure is true.
func MakeBasicHost(listenPort int, protocolID string, randseed int64) (host.Host, error) {

	// If the seed is zero, use real cryptographic randomness. Otherwise, use a
	// deterministic randomness source to make generated keys stay the same
	// across multiple runs
	var r io.Reader
	if randseed == 0 {
		r = rand.Reader
	} else {
		r = mrand.New(mrand.NewSource(randseed))
	}

	// Generate a key pair for this host. We will use it at least
	// to obtain a valid host ID.
	priv, _, err := crypto.GenerateKeyPairWithReader(crypto.RSA, 2048, r)
	if err != nil {
		return nil, err
	}

	opts := []libp2p.Option{
		libp2p.ListenAddrStrings(fmt.Sprintf("/ip4/127.0.0.1/tcp/%d", listenPort)),
		libp2p.Identity(priv),
		libp2p.DisableRelay(),
	}

	if protocolID == plaintext.ID {
		opts = append(opts, libp2p.NoSecurity)
	} else if protocolID == noise.ID {
		tpt, err := noise.New(priv, noise.NoiseKeyPair(nil))
		if err != nil {
			return nil, err
		}
		opts = append(opts, libp2p.Security(protocolID, tpt))
	} else if protocolID == secio.ID {
		tpt, err := secio.New(priv)
		if err != nil {
			return nil, err
		}
		opts = append(opts, libp2p.Security(protocolID, tpt))
	} else {
		return nil, fmt.Errorf("security protocolID '%s' is not supported", protocolID)
	}

	basicHost, err := libp2p.New(context.Background(), opts...)
	if err != nil {
		return nil, err
	}

	// Build host multiaddress
	hostAddr, _ := ma.NewMultiaddr(fmt.Sprintf("/ipfs/%s", basicHost.ID().Pretty()))

	// Now we can build a full multiaddress to reach this host
	// by encapsulating both addresses:
	addr := basicHost.Addrs()[0]
	fullAddr := addr.Encapsulate(hostAddr)
	log.Printf("I am %s\n", fullAddr)
	log.Printf("Now run \"./echo -l %d -d %s -security %s\" on a different terminal\n", listenPort+1, fullAddr, protocolID)

	return basicHost, nil
}
