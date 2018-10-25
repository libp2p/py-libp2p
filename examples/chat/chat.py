import argparse
import Crypto
from Crypto.PublicKey import RSA
from Crypto import Random

# TODO import doesn't quite work here
from host import BasicHost
from network import MultiAddr, Stream, Swarm
from peer import Peer, PeerStore

# def add_addr_to_peerstore(host, addr):
#     """
#     parse peer addr to multiaddr and add it to host's peerstore
#     :param host: a given host instance
#     :param addr: peer addr
#     :return: peer_id assigned to addr
#     """
#     pass

def main(args):
    """
    start running chat node
    """
    
    # create RSA key pair for new host
    random_generator = Random.new().read
    key = RSA.generate(2048, random_generator)
    try:
    	prv_key = key.exportKey("PEM")
    except ValueError:
    	raise RSAValueError("Error in generating RSA key pair")

    # initialize multiaddr
    # initialize Host

    # set stream handler
    # get destination and convert to multiaddr
    # get peer_id from multiaddr
    # add peer multiaddr


def parse_arguments():
    """
    create parser to parse command line args
    :return: parsed arguments
    """
    parser = argparse.ArgumentParser()
    return parser.parse_args(args)

if __name__ == "__main__":
    parsed_args = parse_arguments()
    main(parsed_args)

class RSAValueError(ValueError):
    """Raised when RSA returns Error."""
    pass
		
