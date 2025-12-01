import argparse
import base64
import hashlib
import json
import logging
import os

import multihash
import base58
import multiaddr
import multibase
import requests
import trio

import time
import requests

from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.backends import default_backend
from examples.advanced.network_discover import get_optimal_binding_address
from libp2p import (
    new_host,
)
from libp2p.crypto.keys import PrivateKey
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.network.stream.net_stream import (
    INetStream,
)
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)

# Configure minimal logging
logging.basicConfig(level=logging.WARNING)
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)

PING_PROTOCOL_ID = TProtocol("/ipfs/ping/1.0.0")
PING_LENGTH = 32
RESP_TIMEOUT = 60
PSK = "dffb7e3135399a8b1612b2aaca1c36a3a8ac2cd0cca51ceeb2ced87d308cac6d"


async def handle_ping(stream: INetStream) -> None:
    while True:
        try:
            payload = await stream.read(PING_LENGTH)
            peer_id = stream.muxed_conn.peer_id
            if payload is not None:
                print(f"received ping from {peer_id}")

                await stream.write(payload)
                print(f"responded with pong to {peer_id}")

        except Exception:
            await stream.reset()
            break


async def send_ping(stream: INetStream) -> None:
    try:
        payload = b"\x01" * PING_LENGTH
        print(f"sending ping to {stream.muxed_conn.peer_id}")

        await stream.write(payload)

        with trio.fail_after(RESP_TIMEOUT):
            response = await stream.read(PING_LENGTH)

        if response == payload:
            print(f"received pong from {stream.muxed_conn.peer_id}")

    except Exception as e:
        print(f"error occurred : {e}")


async def run(port: int, destination: str, psk: int, transport: str) -> None:
    from libp2p.utils.address_validation import (
        find_free_port,
        get_available_interfaces,
    )

    if port <= 0:
        port = find_free_port()

    _ = get_available_interfaces(8000)
    _ = get_optimal_binding_address(8000)

    if transport == "tcp":
        listen_addrs = get_available_interfaces(port)
    if transport == "ws":
        listen_addrs = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{port}/ws")]

    if psk == 1:
        host = new_host(listen_addrs=listen_addrs, psk=PSK)
    else:
        host = new_host(listen_addrs=listen_addrs)

    async with host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
        # Start the peer-store cleanup task
        nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)

        if not destination:
            host.set_stream_handler(PING_PROTOCOL_ID, handle_ping)

            # Get all available addresses with peer ID
            all_addrs = host.get_addrs()

            print("Listener ready, listening on:\n")
            for addr in all_addrs:
                print(f"{addr}")

            print(
                f"\nRun this from the same folder in another console:\n\n"
                f"autotls-demo -d {host.get_addrs()[0]} -psk {psk} -t {transport}\n"
            )
            print("Waiting for incoming connection...")
            
            peer_id = host.get_id()
            
            
            # Convert peer-id to multihash `mh`
            # encode `mh` usign CIDv1 with libp2p-key codec 0x72
            # Encode the CID data using multibase base36
            
            mh = base58.b58decode(str(peer_id))
            cid_bytes = bytes([0x01, 0x72]) + mh
            b36_peer_id = multibase.encode("base36", cid_bytes)
            b36_peer_id = b36_peer_id.decode()
            print("Base36 PeerID:", b36_peer_id)
            
            print("\nSTARTING ACME SEQUENCE")

            # ACME new account
            
            ACME_DIRECTORY_URL = "https://acme-staging-v02.api.letsencrypt.org/directory"

            # -------------------------
            # Helpers
            # -------------------------
            def b64u(data: bytes) -> str:
                """Base64url encode without padding, returning str."""
                return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

            def int_to_b64u(n: int) -> str:
                """Encode a big integer as base64url (n or e for JWK)."""
                # convert to big-endian byte sequence (minimum length)
                length = (n.bit_length() + 7) // 8
                return b64u(n.to_bytes(length, "big"))
            
            # -------------------------
            # Key handling
            # -------------------------
            def generate_rsa_key(bits: int = 2048):
                key = rsa.generate_private_key(
                    public_exponent=65537,
                    key_size=bits,
                    backend=default_backend(),
                )
                return key
            
            def load_rsa_key_pem(pem_path: str, password: bytes | None = None):
                with open(pem_path, "rb") as fh:
                    return serialization.load_pem_private_key(fh.read(), password=password, backend=default_backend())

            def jwk_from_rsa_private_key(priv_key):
                pub = priv_key.public_key()
                numbers = pub.public_numbers()
                return {
                    "kty": "RSA",
                    "n": int_to_b64u(numbers.n),
                    "e": int_to_b64u(numbers.e),
                }
                
            # -------------------------
            # ACME JWS creation
            # -------------------------
            def create_jws(protected: dict, payload_obj, priv_key) -> dict:
                """
                payload_obj:
                    - dict → JSON encoded payload
                    - None → empty payload (POST-as-GET)
                """
                protected_b64 = b64u(json.dumps(
                    protected, separators=(",", ":"), sort_keys=True
                ).encode("utf-8"))

                if payload_obj is None:
                    # ACME POST-as-GET requires empty string payload
                    payload_b64 = ""
                    signing_input = f"{protected_b64}.{payload_b64}".encode("ascii")
                else:
                    payload_b64 = b64u(json.dumps(
                        payload_obj, separators=(",", ":"), sort_keys=True
                    ).encode("utf-8"))
                    signing_input = f"{protected_b64}.{payload_b64}".encode("ascii")

                signature = priv_key.sign(
                    signing_input,
                    padding.PKCS1v15(),
                    hashes.SHA256()
                )
                signature_b64 = b64u(signature)

                return {
                    "protected": protected_b64,
                    "payload": payload_b64,
                    "signature": signature_b64
                }

            def get_nonce(directory):
                new_nonce_url = directory["newNonce"]
                nonce_resp = requests.head(new_nonce_url, timeout=10)
                # some servers return nonce in HEAD, some in GET; try HEAD but fallback to GET
                if "Replay-Nonce" in nonce_resp.headers:
                    nonce = nonce_resp.headers["Replay-Nonce"]
                else:
                    nonce_resp_get = requests.get(new_nonce_url, timeout=10)
                    nonce = nonce_resp_get.headers.get("Replay-Nonce")
                if not nonce:
                    raise RuntimeError("Failed to obtain ACME nonce from newNonce endpoint")

                print("Got nonce:", nonce)
                return nonce
                
            # -------------------------
            # Main flow
            # -------------------------
            def acme_new_account_example(priv_key=None, contact_emails=None, terms_agreed=True):
                # 1) key
                if priv_key is None:
                    print("Generating new RSA key (2048)...")
                    priv_key = generate_rsa_key(2048)
                else:
                    print("Using provided RSA key")
                    
                jwk = jwk_from_rsa_private_key(priv_key)
                
                # 2) fetch directory
                r = requests.get(ACME_DIRECTORY_URL, timeout=10)
                r.raise_for_status()
                directory = r.json()
                print("Directory endpoints:", json.dumps(directory, indent=2))
                
                new_nonce_url = directory["newNonce"]
                new_account_url = directory["newAccount"]

                # 3) fetch nonce (GET newNonce returns a replay-nonce header)
                # Many ACME servers require a GET and then read the Replay-Nonce header.
                nonce_resp = requests.head(new_nonce_url, timeout=10)
                # some servers return nonce in HEAD, some in GET; try HEAD but fallback to GET
                if "Replay-Nonce" in nonce_resp.headers:
                    nonce = nonce_resp.headers["Replay-Nonce"]
                else:
                    nonce_resp_get = requests.get(new_nonce_url, timeout=10)
                    nonce = nonce_resp_get.headers.get("Replay-Nonce")
                if not nonce:
                    raise RuntimeError("Failed to obtain ACME nonce from newNonce endpoint")

                print("Got nonce:", nonce)
                
                    # 4) build protected header and payload
                protected = {
                    "alg": "RS256",
                    "typ": "JWT",
                    "nonce": nonce,
                    "url": new_account_url,
                    "jwk": jwk,
                }

                payload = {"termsOfServiceAgreed": bool(terms_agreed)}
                if contact_emails:
                    # contact must be list of mailto: strings per ACME
                    payload["contact"] = [f"mailto:{email}" for email in contact_emails]

                # 5) create JWS
                jws = create_jws(protected, payload, priv_key)
                print("JWS: ",jws)

                # 6) POST to newAccount
                headers = {"Content-Type": "application/jose+json"}
                resp = requests.post(new_account_url, json=jws, headers=headers, timeout=10)

                print("HTTP", resp.status_code)
                try:
                    print("Response headers:", resp.headers)
                    print("Response body:", resp.text)
                except Exception:
                    print("Could not decode response body")

                if not (200 <= resp.status_code < 300):
                    raise RuntimeError(f"ACME newAccount failed: {resp.status_code}: {resp.text}")

                # # server may return account URL in Location header
                account_url = resp.headers.get("Location")
                print("Account location (kid):", account_url)
                return resp, account_url, priv_key, directory
            
            def acme_new_order_for_peerid(b36peerid, directory, priv_key, kid):
                new_nonce_url = directory["newNonce"]
                new_order_url = directory["newOrder"]

                # grab nonce
                nonce_resp = requests.head(new_nonce_url)
                if "Replay-Nonce" not in nonce_resp.headers:
                    nonce_resp = requests.get(new_nonce_url)
                nonce = nonce_resp.headers["Replay-Nonce"]

                domain = f"*.{b36peerid}.libp2p.direct"

                protected = {
                    "alg": "RS256",
                    "kid": kid,
                    "nonce": nonce,
                    "url": new_order_url
                }

                payload = {
                    "identifiers": [
                        {
                            "type": "dns",
                            "value": domain
                        }
                    ]
                }
                
                jws = create_jws(protected, payload, priv_key)
                resp = requests.post(
                    new_order_url,
                    json=jws,
                    headers={"Content-Type": "application/jose+json"},
                    timeout=10
                )
                print("\n\n")

                print("HTTP", resp.status_code)
                
                try:
                    print("Response headers:", resp.headers)
                    print("Response body:", resp.text)
                except Exception:
                    print("Could not decode response body")
                
                order_url = resp.headers["Location"]
                
                print("\n\n")
                
                resp.raise_for_status()
                return resp.json(), order_url


            def acme_get_dns01_challenge(auth_url, directory, priv_key, kid, jwk_thumbprint):
                new_nonce_url = directory["newNonce"]

                # POST-as-GET with empty payload
                # First fetch nonce
                nonce_resp = requests.head(new_nonce_url)
                if "Replay-Nonce" not in nonce_resp.headers:
                    nonce_resp = requests.get(new_nonce_url)
                nonce = nonce_resp.headers["Replay-Nonce"]
                print("New Nonce created in get_dns_chanllenge")

                protected = {
                    "alg": "RS256",
                    "kid": kid,
                    "nonce": nonce,
                    "url": auth_url
                }

                jws = create_jws(protected, None, priv_key)

                resp = requests.post(
                    auth_url,
                    json=jws,
                    headers={"Content-Type": "application/jose+json"},
                    timeout=10
                )
                
                print("\n\n")

                print("HTTP", resp.status_code)
                
                try:
                    print("Response headers:", resp.headers)
                    print("Response body:", resp.text)
                except Exception:
                    print("Could not decode response body")
                    
                print("\n\n")
                
                resp.raise_for_status()
                
                auth = resp.json()

                # find dns-01 challenge
                dns01 = None
                for ch in auth.get("challenges", []):
                    if ch.get("type") == "dns-01":
                        dns01 = ch
                        break

                if dns01 is None:
                    raise RuntimeError("dns-01 challenge not found")

                token = dns01["token"]
                chall_url = dns01["url"]
                key_auth = f"{token}.{jwk_thumbprint}"

                return dns01, key_auth, chall_url
            
            def compute_jwk_thumbprint(jwk):
                # JWK must contain only these 3 keys, *sorted*, per RFC 7638
                ordered = {
                    "e": jwk["e"],
                    "kty": jwk["kty"],
                    "n": jwk["n"]
                }
                
                jwk_json = json.dumps(ordered, separators=(",", ":"), sort_keys=True)
                digest = hashlib.sha256(jwk_json.encode("utf-8")).digest()
                return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
            
            
            def send_autotls_challenge_libp2p(key_authorization, peer_privkey: PrivateKey, multiaddrs: list):
                import base64
                import os
                import requests

                def base64url_encode(b: bytes) -> str:
                    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")

                broker_url = "https://registration.libp2p.direct/v1/_acme-challenge"

                # Fetch challenge from broker (WWW-Authenticate)
                resp = requests.get(broker_url, timeout=10)
                print(resp.headers)
                if resp.status_code != 401:
                    raise RuntimeError(f"Expected 401 challenge, got {resp.status_code}")

                www_auth = resp.headers.get("Www-Authenticate", "")
                print("Raw WWW-Authenticate:", www_auth)

                # parse key=value pairs safely
                parts = {}
                for part in www_auth.split(","):
                    if "=" in part:
                        k, v = part.strip().split("=", 1)
                        parts[k.strip()] = v.strip('"')

                # now check which key exists
                challenge_node = parts.get("libp2p-PeerID challenge-client") or parts.get("challenge-client")
                if not challenge_node:
                    raise RuntimeError("Could not find challenge node in WWW-Authenticate header")

                broker_pubkey = parts.get("public-key")
                opaque = parts.get("opaque")

                print("\n\n\nchallenge: ", challenge_node )
                print("broker: ", broker_pubkey)
                print("opaque: ", opaque)

                # Random 32-char challenge
                challenge_server = base64url_encode(os.urandom(24))

                # Signature
                sig_message = (
                    f"challenge-node={challenge_node}".encode() +
                    f"hostname=registration.libp2p.direct".encode() +
                    f"server-public-key={broker_pubkey}".encode()
                )
                sig_bytes = peer_privkey.sign(sig_message)
                sig_b64 = base64url_encode(sig_bytes)
                
                peer_pubkey = peer_privkey.get_public_key()

                # Authorization header
                headers = {
                    "Content-Type": "application/json",
                    "User-Agent": "helia/2.0.0",
                    "Authorization": (
                        f'libp2p-PeerID public-key="{base64url_encode(peer_pubkey.to_bytes())}", '
                        f'opaque="{opaque}", '
                        f'challenge-server="{challenge_server}", '
                        f'sig="{sig_b64}"'
                    )
                }

                payload = {
                    "value": key_authorization,
                    "addresses": multiaddrs
                }

                # POST to broker
                resp = requests.post(broker_url, json=payload, headers=headers, timeout=10)
                
                print("\n\n")

                print("HTTP", resp.status_code)
                
                try:
                    print("Response headers:", resp.headers)
                    print("Response body:", resp.text)
                except Exception:
                    print("Could not decode response body")
                
                # order_url = resp.headers["Location"]
                
                print("\n\n")
          
                resp.raise_for_status()

                # # Extract bearer token
                # auth_info = resp.headers.get("Authentication-Info", "")
                # token = None
                # for part in auth_info.split(","):
                #     if part.strip().startswith("bearer="):
                #         token = part.split("=", 1)[1].strip('"')
                #         break
                # if not token:
                #     raise RuntimeError("Bearer token not found in broker response")

                # print("Bearer token from broker:", token)
                # return token
                        
            priv = generate_rsa_key(2048)

            try:
                acme_new_account_example(priv, contact_emails=["abhinavagarwalla6@gmail.com"])
                resp, account_url, key, directory = acme_new_account_example(priv, contact_emails=[])
                print("Success. Account URL:", account_url, "\n")
                
                new_order_response, order_url = acme_new_order_for_peerid(b36_peer_id, directory, priv, account_url)
                print("New order response: ", new_order_response)
                
                jwk = jwk_from_rsa_private_key(priv)
                jwk_thumprint = compute_jwk_thumbprint(jwk)
                auth_url = new_order_response["authorizations"][0]
                finalize_url = new_order_response["finalize"]
                
                dns01, key_auth, chall_url = acme_get_dns01_challenge(auth_url, directory, priv, account_url, jwk_thumprint)
                
                print("\n\n")
                
                print("DNS-01: ", dns01)
                print("Key-Authorization: ", key_auth)
                
                print("\n\n")
                
                print("orderUrl: ", order_url)
                print("chalUrl: ", chall_url)
                print("finalizeUrl: ", finalize_url)
                
                print("\n\nNOW STARTS THE BROKER THING")
                
                host_private_key = host.get_private_key()
                bearer_token = send_autotls_challenge_libp2p(key_auth, host_private_key, [])
        
                
            except Exception as e:
                print("Error:", e)
            
        else:
            maddr = multiaddr.Multiaddr(destination)
            info = info_from_p2p_addr(maddr)
            await host.connect(info)
            stream = await host.new_stream(info.peer_id, [PING_PROTOCOL_ID])

            nursery.start_soon(send_ping, stream)

            return

        await trio.sleep_forever()


def main() -> None:
    description = """
    This program demonstrates a simple p2p ping application using libp2p.
    To use it, first run 'python ping.py -p <PORT>', where <PORT> is the port number.
    Then, run another instance with 'python ping.py -p <ANOTHER_PORT> -d <DESTINATION>',
    where <DESTINATION> is the multiaddress of the previous listener host.
    """

    example_maddr = (
        "/ip4/[HOST_IP]/tcp/8000/p2p/QmQn4SwGkDZKkUEpBRBvTmheQycxAHJUNmVEnjA2v1qe8Q"
    )

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-p", "--port", default=0, type=int, help="source port number")

    parser.add_argument(
        "-d",
        "--destination",
        type=str,
        help=f"destination multiaddr string, e.g. {example_maddr}",
    )

    parser.add_argument(
        "-psk", "--psk", default=0, type=int, help="Enable PSK in the transport layer"
    )

    parser.add_argument(
        "-t",
        "--transport",
        default="tcp",
        type=str,
        help="Choose the transport layer for ping TCP/WS",
    )

    args = parser.parse_args()

    try:
        trio.run(run, *(args.port, args.destination, args.psk, args.transport))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
