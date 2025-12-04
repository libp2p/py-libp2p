import argparse
import base64
import hashlib
import json
import logging
import os
import base58
import multiaddr
import multibase
import requests
import trio
import base64
import requests
from urllib.parse import urlparse
import re

import time
import requests

from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.backends import default_backend
from examples.advanced.network_discover import get_optimal_binding_address
from libp2p import (
    new_host,
)
from libp2p.crypto.keys import KeyType, PrivateKey, PublicKey
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.identity.identify.identify import identify_handler_for, ID as IDENTIFY_PROTOCOL_ID
from libp2p.identity.identify.pb.identify_pb2 import Identify
from libp2p.network.stream.net_stream import (
    INetStream,
)
from libp2p.peer.envelope import debug_dump_envelope, unmarshal_envelope
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
DIRECTORY = {}
ACME_DIRECTORY_URL = "https://acme-staging-v02.api.letsencrypt.org/directory"
PEER_ID_AUTH_SCHEME = "libp2p-PeerID="

# --------------
# IDENTIFY-UTILS
def decode_multiaddrs(raw_addrs):
    """Convert raw listen addresses into human-readable multiaddresses."""
    decoded_addrs = []
    for addr in raw_addrs:
        try:
            decoded_addrs.append(str(multiaddr.Multiaddr(addr)))
        except Exception as e:
            decoded_addrs.append(f"Invalid Multiaddr ({addr}): {e}")
    return decoded_addrs

def print_identify_response(identify_response: Identify):
    """Pretty-print Identify response."""
    public_key_b64 = base64.b64encode(identify_response.public_key).decode("utf-8")
    listen_addrs = decode_multiaddrs(identify_response.listen_addrs)
    signed_peer_record = unmarshal_envelope(identify_response.signedPeerRecord)
    try:
        observed_addr_decoded = decode_multiaddrs([identify_response.observed_addr])
    except Exception:
        observed_addr_decoded = identify_response.observed_addr
    print(
        f"Identify response:\n"
        f"  Public Key (Base64): {public_key_b64}\n"
        f"  Listen Addresses: {listen_addrs}\n"
        f"  Protocols: {list(identify_response.protocols)}\n"
        f"  Observed Address: "
        f"{observed_addr_decoded if identify_response.observed_addr else 'None'}\n"
        f"  Protocol Version: {identify_response.protocol_version}\n"
        f"  Agent Version: {identify_response.agent_version}"
    )

    debug_dump_envelope(signed_peer_record)

# -------------

def dns01_key_authorization_to_txt(key_auth: str) -> str:

    digest = hashlib.sha256(key_auth.encode("utf-8")).digest()
    txt = base64.urlsafe_b64encode(digest).decode("utf-8")
    txt = txt.rstrip("=")
    return txt

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

def pubkey_to_protobuf_bytes(pub: PublicKey) -> bytes:
    return pub.serialize()  # already protobuf-encoded

def encode_auth_params(params: dict) -> str:
    # JS does "key=value" pairs, comma-separated
    parts = []
    for k, v in params.items():
        parts.append(f'{k}="{v}"')
    return ", ".join(parts)

def decode_auth_header(header: str) -> dict:
    # strip scheme prefix
    if header.startswith("libp2p-PeerID "):
        header = header[len("libp2p-PeerID "):]

    # match key="value" patterns safely
    pattern = r'(\w[\w-]*)="([^"]*)"'
    matches = re.findall(pattern, header)

    return {k: v for k, v in matches}

def make_signature_payload(fields: list[tuple[str, bytes | str]]) -> bytes:
    out = bytearray()
    out.extend(PEER_ID_AUTH_SCHEME.encode())
    for k, v in fields:
        out.extend(k.encode())
        if isinstance(v, str):
            out.extend(v.encode())
        else:
            out.extend(v)
    return bytes(out)

def pubkey_from_protobuf_bytes(b: bytes) -> PublicKey:
    pb = PublicKey.deserialize_from_protobuf(b)
    # Now construct a proper PublicKey instance:
    key_type = KeyType(pb.key_type)
    if key_type == KeyType.Ed25519:
        from libp2p.crypto.ed25519 import Ed25519PublicKey
        return Ed25519PublicKey(pb.data)
    else:
        raise ValueError("Unsupported key type yet")
    
def get_nonce():
    new_nonce_url = DIRECTORY["newNonce"]
    nonce_resp = requests.head(new_nonce_url, timeout=10)
    # some servers return nonce in HEAD, some in GET; try HEAD but fallback to GET
    if "Replay-Nonce" in nonce_resp.headers:
        nonce = nonce_resp.headers["Replay-Nonce"]
    else:
        nonce_resp_get = requests.get(new_nonce_url, timeout=10)
        nonce = nonce_resp_get.headers.get("Replay-Nonce")
    if not nonce:
        raise RuntimeError("Failed to obtain ACME nonce from newNonce endpoint")
    return nonce

def b64u(data: bytes) -> str:
    """Base64url encode without padding, returning str."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

def int_to_b64u(n: int) -> str:
    """Encode a big integer as base64url (n or e for JWK)."""
    # convert to big-endian byte sequence (minimum length)
    length = (n.bit_length() + 7) // 8
    return b64u(n.to_bytes(length, "big"))

def generate_rsa_key(bits: int = 2048):
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=bits,
        backend=default_backend(),
    )
    return key

def jwk_from_rsa_private_key(priv_key):
    pub = priv_key.public_key()
    numbers = pub.public_numbers()
    return {
        "kty": "RSA",
        "n": int_to_b64u(numbers.n),
        "e": int_to_b64u(numbers.e),
    }

def create_jws(protected, payload, priv_key) -> dict:
    """
    payload_obj:
        - dict → JSON encoded payload
        - None → empty payload (POST-as-GET)
    """
    protected_b64 = b64u(json.dumps(
        protected, separators=(",", ":"), sort_keys=True
    ).encode("utf-8"))

    if payload is None:
        # ACME POST-as-GET requires empty string payload
        payload_b64 = ""
        signing_input = f"{protected_b64}.{payload_b64}".encode("ascii")
    else:
        payload_b64 = b64u(json.dumps(
            payload, separators=(",", ":"), sort_keys=True
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

class ClientInitiatedHandshake:
    def __init__(self, private_key: PrivateKey, hostname: str):
        self.private_key = private_key
        self.hostname = hostname
        self.challenge = os.urandom(32).hex()
        self.state = "init"
        self.server_id = None

    def get_challenge_header(self) -> str:
        self.state = "challenge-server"

        pub_pb = pubkey_to_protobuf_bytes(self.private_key.get_public_key())
        pub_b64 = base64.urlsafe_b64encode(pub_pb).decode()

        params = encode_auth_params({
            "challenge-server": self.challenge,
            "public-key": pub_b64,
        })

        return f"libp2p-PeerID {params}"


    def verify_server(self, header: str) -> str:
        from libp2p.peer.id import ID

        if self.state != "challenge-server":
            raise Exception("Handshake order wrong")

        msg = decode_auth_header(header)

        server_pub_b64 = msg["public-key"]
        chall_client   = msg["challenge-client"]
        sig_b64        = msg["sig"]

        server_pub_pb = base64.urlsafe_b64decode(server_pub_b64)
        server_pub = pubkey_from_protobuf_bytes(server_pub_pb)
        self.server_id = ID.from_pubkey(server_pub)
        sig = base64.urlsafe_b64decode(sig_b64)
        
        # TODO: NEED TO VERIFY THE SIG THAT SERVER SENT
        
        # Marshal our public key (protobuf)
        client_pub_pb = pubkey_to_protobuf_bytes(self.private_key.get_public_key())
        
        response_payload = make_signature_payload([
            ("challenge-client=", chall_client),
            ("#hostname=", "registration.libp2p.direct6"),            
            ("server-public-key=", server_pub_pb),
        ])
        
        client_sig = self.private_key.sign(response_payload)
        client_sig_b64 = base64.urlsafe_b64encode(client_sig).decode()

        self.state = "respond-to-server"

        return encode_auth_params({
            "opaque": msg["opaque"],
            "sig": client_sig_b64,
        })

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
        
    # Set up identify handler with specified format
        # Set use_varint_format = False, if want to checkout the Signed-PeerRecord
    identify_handler = identify_handler_for(
        host, use_varint_format=True
    )

    async with host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
        # Start the peer-store cleanup task
        nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)

        if not destination:
            host.set_stream_handler(IDENTIFY_PROTOCOL_ID, identify_handler)
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
            
            print("\nBase36 PeerID:", b36_peer_id)
            
            def acme_new_account(priv_key = None):

                if priv_key is None:
                    print("\nGENERATING RSA-KEY (2048)...")
                    priv_key = generate_rsa_key(2048)
                else:
                    print("\nUSING PROVIDED RSA KEY")
                    
                print("STARTING ACME ACCOUTN CREATION SEQUENCE...")
                                    
                # Fetch directory
                r = requests.get(ACME_DIRECTORY_URL, timeout=10)
                r.raise_for_status()
                
                global DIRECTORY
                DIRECTORY = r.json()
                
                # Create JWS
                nonce = get_nonce()
                new_account_url = DIRECTORY["newAccount"]
                jwk = jwk_from_rsa_private_key(priv_key)
                
                protected = {
                    "alg": "RS256",
                    "typ": "JWT",
                    "nonce": nonce,
                    "url": new_account_url,
                    "jwk": jwk,
                }
                payload = {"termsOfServiceAgreed": True}
                jws = create_jws(protected, payload, priv_key)

                # POST to newAccount || Fetch the account URL
                headers = {"Content-Type": "application/jose+json"}
                resp = requests.post(DIRECTORY["newAccount"], json=jws, headers=headers, timeout=10)

                if not (200 <= resp.status_code < 300):
                    raise RuntimeError(f"ACME newAccount failed: {resp.status_code}: {resp.text}")

                account_url = resp.headers.get("Location")
                print("\nACCOUNT-URL:", account_url)
                return account_url, priv_key
            
            def acme_new_order_for_peerid(b36peerid, priv_key, kid):
                new_order_url = DIRECTORY["newOrder"]
                nonce = get_nonce()
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
                
                order_url = resp.headers["Location"]
                auth_url = resp.json()["authorizations"][0]
                finalize_url = resp.json()["finalize"]


                print("ORDER-URL: ", order_url)
                print("AUTH-URL: ", auth_url)
                print("FINALIZE-URL: ", finalize_url)
                                
                resp.raise_for_status()
                return order_url, auth_url, finalize_url

            def acme_get_dns01_challenge(auth_url, priv_key, kid, jwk_thumbprint):
                
                print("\nGETTING THE DNS-01 CHALLENGE FROM ACME...")
                
                # POST-as-GET with empty payload   
                nonce = get_nonce()
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
                                       
                auth = resp.json()

                # Find DNS-01 CHALLENGE
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
                key_auth = dns01_key_authorization_to_txt(key_auth)

                print("\nCHALL-URL: ", chall_url)
                print("DNS-TOKEN: ", token)
                print("JWK-THUMBPRINT: ", jwk_thumbprint)
                print("KEY-AUTH: ", key_auth)

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
            
            def http_peer_id_auth(private_key: PrivateKey, key_auth, addrs):
                
                print("\nINITIATION PEER-ID AUTHENTICATION WITH AUTO-TLS BROKER...")
                
                url = "https://registration.libp2p.direct/v1/_acme-challenge"
                hostname = urlparse(url).hostname
                hs = ClientInitiatedHandshake(private_key, hostname)
                
                header={
                    "Authorization": hs.get_challenge_header()
                }
                resp = requests.options(url, headers=header)
                                
                www = resp.headers.get("Www-Authenticate")
                if not www:
                    raise Exception("Missing WWW-Authenticate")

                # Verify server and respond
                body = {
                    "value": key_auth,
                    "addresses": addrs
                }
                
                header={
                    "User-Agent": "py-libp2p/example/autotls",
                    "Authorization": "libp2p-PeerID " + hs.verify_server(www)
                }                
                resp = requests.post(url, headers=header, data=json.dumps(body))
                print("\n\n", resp.request.headers, resp.request.body)
            
                # Extract BEARER-TOKEN
                auth_info = resp.headers.get("Authentication-Info")
                bearer = None
                if auth_info:
                    bearer = decode_auth_header(auth_info).get("bearer")
                    
                print("\nSERVER_PEER_ID: ", hs.server_id)
                print("BEARER TOKEN: ", bearer)

                return hs.server_id, bearer     
 
            def send_dns_challenge(bearer, auth_url, chall_url, key_auth, public_addrs):
                # url = "https://registration.libp2p.direct/v1/dns01"
                url = "https://registration.libp2p.direct/v1/_acme-challenge"

                headers = {
                    "Authorization": f"Bearer {bearer}",
                    "Content-Type": "application/json",
                }

                # body = {
                #     "auth_url": auth_url,
                #     "challenge_url": chall_url,
                #     "key_authorization": key_auth,
                # }
                
                body = {
                  "value": key_auth,
                  "addresses": public_addrs  
                }

                r = requests.post(url, headers=headers, json=body)
                print("\nBROKER RESPONSE:", r, r.status_code, r.headers)
                return r

 
            try:
                account_url, priv_key = acme_new_account(None)
                order_url, auth_url, finalize_url = acme_new_order_for_peerid(b36_peer_id, priv_key, account_url)
                
                jwk = jwk_from_rsa_private_key(priv_key)
                jwk_thumprint = compute_jwk_thumbprint(jwk)
                
                dns01, key_auth, chall_url = acme_get_dns01_challenge(auth_url, priv_key, account_url, jwk_thumprint)     
                public_addrs = [f"/ip4/13.126.88.127/tcp/{port}/p2p/{host.get_id()}"]
                                     
                server_id, bearer = http_peer_id_auth(host.get_private_key(), key_auth, public_addrs)
                                
                # response = send_dns_challenge(bearer, auth_url, chall_url, key_auth, public_addrs)
                
                
                                
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

# try:
#     print("\nResponse headers:", resp.headers)
#     print("\nResponse body:", resp.text)
# except Exception:
#     print("Could not decode response body")