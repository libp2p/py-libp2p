#!/usr/bin/env python3

import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from libp2p.bitswap.cid import (
    CODEC_DAG_PB,
    CODEC_RAW,
    analyze_cid_collection,
    compute_cid_v0,
    compute_cid_v1,
    detect_cid_encoding_format,
    recompute_cid_from_data,
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
        info = detect_cid_encoding_format(cid)
        if "error" in info:
            logger.info("%s: %s", name, info["error"])
        else:
            logger.info(
                "%s: version=%s, codec=%s, encoding=%s, is_breaking=%s",
                name,
                info["version"],
                info["codec_name"],
                info["encoding"],
                info["is_breaking"],
            )

    try:
        recomputed = recompute_cid_from_data(cid_v1_raw, data)
        logger.info("Recomputed CID matches original: %s", cid_v1_raw == recomputed)
    except ValueError as e:
        logger.info("Recompute error: %s", e)

    collection = [cid_v0, cid_v1_raw, cid_v1_dag_pb]
    analysis = analyze_cid_collection(collection)
    logger.info(
        "Collection: total=%s, backward_compatible=%s, breaking_change=%s, by_codec=%s",
        analysis["total"],
        analysis["backward_compatible"],
        analysis["breaking_change"],
        analysis["by_codec"],
    )


if __name__ == "__main__":
    main()
