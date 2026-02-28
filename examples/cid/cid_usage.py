#!/usr/bin/env python3

import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from libp2p.bitswap.cid import (
    CODEC_DAG_PB,
    CODEC_RAW,
    compute_cid_v0,
    compute_cid_v1,
    compute_cid_v1_obj,
    parse_cid_codec,
    parse_cid_version,
    verify_cid,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    data = b"Hello, libp2p!"

    cid_v0 = compute_cid_v0(data)
    cid_v1_raw = compute_cid_v1(data, codec=CODEC_RAW)
    cid_v1_dag_pb = compute_cid_v1(data, codec=CODEC_DAG_PB)

    logger.info("CIDv0: %s", cid_v0.hex())
    logger.info("CIDv1 (raw): %s", cid_v1_raw.hex())
    logger.info("CIDv1 (dag-pb): %s", cid_v1_dag_pb.hex())

    logger.info("verify_cid(cid_v0, data): %s", verify_cid(cid_v0, data))
    logger.info("verify_cid(cid_v1_raw, data): %s", verify_cid(cid_v1_raw, data))
    logger.info("verify_cid(cid_v1_raw, b'bad'): %s", verify_cid(cid_v1_raw, b"bad"))

    for name, cid in [
        ("CIDv0", cid_v0),
        ("CIDv1 raw", cid_v1_raw),
        ("CIDv1 dag-pb", cid_v1_dag_pb),
    ]:
        logger.info(
            "%s: version=%s, codec=%s",
            name,
            parse_cid_version(cid),
            parse_cid_codec(cid),
        )

    cid_obj = compute_cid_v1_obj(data, codec=CODEC_RAW)
    logger.info("CIDv1 object text form: %s", cid_obj)
    logger.info(
        "CIDv1 object bytes == compute_cid_v1 bytes: %s", cid_obj.buffer == cid_v1_raw
    )


if __name__ == "__main__":
    main()
