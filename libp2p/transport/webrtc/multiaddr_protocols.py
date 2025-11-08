"""
Register WebRTC-related protocols with multiaddr.
This module extends py-multiaddr with WebRTC protocol definitions.
"""

import logging
from typing import Any

logger = logging.getLogger("libp2p.transport.webrtc.multiaddr_protocols")

WEBRTC_PROTOCOL_CODE = 281  # 0x0119
WEBRTC_DIRECT_PROTOCOL_CODE = 280  # 0x0118
CERTHASH_PROTOCOL_CODE = 466  # 0x01D2


def register_webrtc_protocols() -> None:
    """
    Register WebRTC protocols with the multiaddr protocol table.
    Create multiaddrs with /webrtc, /webrtc-direct, and /certhash components.
    """
    try:
        from multiaddr.protocols import REGISTRY, Protocol

        # Create add_protocol function as a convenience wrapper
        add_protocol = REGISTRY.add

        webrtc_protocol = Protocol(
            code=WEBRTC_PROTOCOL_CODE,
            name="webrtc",
            codec=None,
        )

        webrtc_direct_protocol = Protocol(
            code=WEBRTC_DIRECT_PROTOCOL_CODE,
            name="webrtc-direct",
            codec=None,
        )

        # Certhash is variable-length (contains base64url string values)
        # Use 'fspath' codec for variable-length strings
        certhash_protocol = Protocol(
            code=CERTHASH_PROTOCOL_CODE,
            name="certhash",
            codec="fspath",  # Variable-leng str codec that accepts base64url
        )

        try:
            add_protocol(webrtc_protocol)
            add_protocol(webrtc_direct_protocol)
            add_protocol(certhash_protocol)
            logger.info(
                "Successfully registered WebRTC protocols with multiaddr (add_protocol)"
            )
        except Exception:
            logger.debug("add_protocol failed; fallback alternative registration")
            register_webrtc_protocols_fallback()

    except Exception:
        logger.warning(
            "Could not import multiaddr protocols; using fallback registration."
        )
        register_webrtc_protocols_fallback()


def register_webrtc_protocols_fallback() -> None:
    """
    Fallback method to register WebRTC protocols for older multiaddr versions.
    Directly modifies the protocols table.
    """
    try:
        from multiaddr import protocols

        if hasattr(protocols, "protocol_with_name"):
            try:
                protocols.protocol_with_name("webrtc")
                logger.debug("WebRTC protocol already registered")
                return
            except Exception:
                pass

        Protocol = getattr(protocols, "Protocol", None)
        if Protocol is not None:
            try:
                webrtc_proto = Protocol(
                    code=WEBRTC_PROTOCOL_CODE,
                    name="webrtc",
                    codec=None,
                )
                webrtc_direct_proto = Protocol(
                    code=WEBRTC_DIRECT_PROTOCOL_CODE,
                    name="webrtc-direct",
                    codec=None,
                )
                certhash_proto = Protocol(
                    code=CERTHASH_PROTOCOL_CODE,
                    name="certhash",
                    codec="fspath",  # Variable-length string codec
                )
            except Exception:
                Protocol = None

        if Protocol is None:

            def _make_proto(code: int, name: str, size: int = 0) -> Any:
                class ProtocolLike:
                    def __init__(self) -> None:
                        self.code = code
                        self.name = name
                        self.size = size
                        self.vcode = None
                        self.codec = None
                        self.path = None

                return ProtocolLike()

            webrtc_proto = _make_proto(WEBRTC_PROTOCOL_CODE, "webrtc")
            webrtc_direct_proto = _make_proto(
                WEBRTC_DIRECT_PROTOCOL_CODE, "webrtc-direct"
            )
            certhash_proto = _make_proto(CERTHASH_PROTOCOL_CODE, "certhash", size=-1)

        reg = getattr(protocols, "REGISTRY", None)
        if reg is not None:
            try:
                ProtocolCls = getattr(protocols, "Protocol", None)
                if ProtocolCls is not None:
                    try:
                        wp = ProtocolCls(
                            code=WEBRTC_PROTOCOL_CODE,
                            name="webrtc",
                            codec=None,
                        )
                        wpd = ProtocolCls(
                            code=WEBRTC_DIRECT_PROTOCOL_CODE,
                            name="webrtc-direct",
                            codec=None,
                        )
                        wpc = ProtocolCls(
                            code=CERTHASH_PROTOCOL_CODE,
                            name="certhash",
                            codec="fspath",
                        )
                    except Exception:
                        wp = webrtc_proto
                        wpd = webrtc_direct_proto
                        wpc = certhash_proto
                else:
                    wp = webrtc_proto
                    wpd = webrtc_direct_proto
                    wpc = certhash_proto

                try:
                    is_locked = getattr(reg, "locked", False)
                except Exception:
                    is_locked = False

                target_reg = reg
                if is_locked and hasattr(reg, "copy"):
                    try:
                        target_reg = reg.copy(unlock=True)
                    except Exception as e:
                        logger.debug(f"Could not copy/unlock REGISTRY: {e}")

                if hasattr(target_reg, "add"):
                    try:
                        target_reg.add(wp)
                        target_reg.add(wpd)
                        target_reg.add(wpc)
                        if target_reg is not reg:
                            protocols.REGISTRY = target_reg

                        logger.info("Successfully registered WebRTC protocols")
                        return
                    except Exception as e:
                        logger.debug(f"REGISTRY.add failed: {e}")
            except Exception as e:
                logger.debug(f"Error while attempting REGISTRY registration: {e}")

        if not hasattr(protocols, "PROTOCOLS") or not isinstance(
            getattr(protocols, "PROTOCOLS", None), list
        ):
            protocols.PROTOCOLS = []

        # Access the registry's internal dictionaries
        reg = getattr(protocols, "REGISTRY", None)
        if reg is not None:
            if not hasattr(reg, "_names_to_protocols") or not isinstance(
                getattr(reg, "_names_to_protocols", None), dict
            ):
                reg._names_to_protocols = {}

            if not hasattr(reg, "_codes_to_protocols") or not isinstance(
                getattr(reg, "_codes_to_protocols", None), dict
            ):
                reg._codes_to_protocols = {}

        # Append and update maps
        try:
            # Append to PROTOCOLS only if not already present (avoid duplicates)
            def _exists(p_list: list[Any], proto: Any) -> bool:
                for p in p_list:
                    if getattr(p, "name", None) == getattr(
                        proto, "name", None
                    ) or getattr(p, "code", None) == getattr(proto, "code", None):
                        return True
                return False

            if not _exists(protocols.PROTOCOLS, webrtc_proto):
                protocols.PROTOCOLS.append(webrtc_proto)
            if not _exists(protocols.PROTOCOLS, webrtc_direct_proto):
                protocols.PROTOCOLS.append(webrtc_direct_proto)
            if not _exists(protocols.PROTOCOLS, certhash_proto):
                protocols.PROTOCOLS.append(certhash_proto)

            # Update registry dictionaries if available
            if reg is not None:
                name = getattr(webrtc_proto, "name", None)
                code = getattr(webrtc_proto, "code", None)
                if name is not None:
                    reg._names_to_protocols[name] = webrtc_proto
                if code is not None:
                    reg._codes_to_protocols[code] = webrtc_proto

                name2 = getattr(webrtc_direct_proto, "name", None)
                code2 = getattr(webrtc_direct_proto, "code", None)
                if name2 is not None:
                    reg._names_to_protocols[name2] = webrtc_direct_proto
                if code2 is not None:
                    reg._codes_to_protocols[code2] = webrtc_direct_proto

                name3 = getattr(certhash_proto, "name", None)
                code3 = getattr(certhash_proto, "code", None)
                if name3 is not None:
                    reg._names_to_protocols[name3] = certhash_proto
                if code3 is not None:
                    reg._codes_to_protocols[code3] = certhash_proto

            # Provide protocol_with_name helper if missing
            if not hasattr(protocols, "protocol_with_name"):

                def protocol_with_name(name: str) -> Any:
                    if reg is not None and hasattr(reg, "_names_to_protocols"):
                        if name in reg._names_to_protocols:
                            return reg._names_to_protocols[name]
                    for p in protocols.PROTOCOLS:
                        if getattr(p, "name", None) == name:
                            return p
                    raise ValueError(f"No protocol with name '{name}' found")

                protocols.protocol_with_name = protocol_with_name

                # Also try to inform REGISTRY
                # (so protocol_with_name which calls REGISTRY.find_by_name works)
                if reg is not None:
                    try:
                        # Try adding ProtocolCls instances to the registry if possible
                        ProtocolCls = getattr(protocols, "Protocol", None)
                        if ProtocolCls is not None:
                            try:
                                rp = ProtocolCls(
                                    code=getattr(
                                        webrtc_proto, "code", WEBRTC_PROTOCOL_CODE
                                    ),
                                    name=getattr(webrtc_proto, "name", "webrtc"),
                                    codec=None,
                                )
                                rpd = ProtocolCls(
                                    code=getattr(
                                        webrtc_direct_proto,
                                        "code",
                                        WEBRTC_DIRECT_PROTOCOL_CODE,
                                    ),
                                    name=getattr(
                                        webrtc_direct_proto, "name", "webrtc-direct"
                                    ),
                                    codec=None,
                                )
                                rpc = ProtocolCls(
                                    code=getattr(
                                        certhash_proto, "code", CERTHASH_PROTOCOL_CODE
                                    ),
                                    name=getattr(certhash_proto, "name", "certhash"),
                                    codec=None,
                                )
                            except Exception:
                                rp = webrtc_proto
                                rpd = webrtc_direct_proto
                                rpc = certhash_proto
                        else:
                            rp = webrtc_proto
                            rpd = webrtc_direct_proto
                            rpc = certhash_proto

                        if hasattr(reg, "add"):
                            try:
                                reg.add(rp)
                                reg.add(rpd)
                                reg.add(rpc)
                            except Exception:
                                # try aliases if available
                                try:
                                    if hasattr(reg, "add_alias_name"):
                                        reg.add_alias_name(
                                            rp, getattr(rp, "name", None)
                                        )
                                        reg.add_alias_name(
                                            rpd, getattr(rpd, "name", None)
                                        )
                                        reg.add_alias_name(
                                            rpc, getattr(rpc, "name", None)
                                        )
                                except Exception:
                                    pass
                    except Exception:
                        pass

                logger.info(
                    "Successfully registered WebRTC protocols (PROTOCOLS list fallback)"
                )
                return
            return
        except Exception as e:
            logger.error(f"Fallback registration failed while updating PROTOCOLS: {e}")

    except Exception as e:
        logger.error(f"Fallback registration failed: {e}")


# Auto-register on module import
try:
    register_webrtc_protocols()
except Exception as e:
    logger.warning(f"Auto-registration of WebRTC protocols failed: {e}")
