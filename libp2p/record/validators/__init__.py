from libp2p.record.validators.ipns import IPNSValidator
from libp2p.record.validators.pubkey import PublicKeyValidator
from libp2p.record.validator import NamespacedValidator

registry = {
    "/ipns/": IPNSValidator(),
    "/pk/": PublicKeyValidator(),
}

namespaced_validator = NamespacedValidator(registry)