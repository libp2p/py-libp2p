"""
Register WebRTC-related protocols with multiaddr.
This module extends py-multiaddr with WebRTC protocol definitions.
"""
import logging
from typing import Any

logger = logging.getLogger("libp2p.transport.webrtc.multiaddr_protocols")

WEBRTC_PROTOCOL_CODE = 280
WEBRTC_DIRECT_PROTOCOL_CODE = 281

def register_webrtc_protocols() -> None:
    """
    Register WebRTC protocols with the multiaddr protocol table.
    This allows creating multiaddrs with /webrtc and /webrtc-direct components.
    """
    try:
        from multiaddr.protocols import Protocol, add_protocol  # type: ignore

        webrtc_protocol = Protocol(
            code=WEBRTC_PROTOCOL_CODE,
            name="webrtc",
            size=0,
        )

        webrtc_direct_protocol = Protocol(
            code=WEBRTC_DIRECT_PROTOCOL_CODE,
            name="webrtc-direct",
            size=0,
        )

        try:
            add_protocol(webrtc_protocol)
            add_protocol(webrtc_direct_protocol)
            logger.info("Successfully registered WebRTC protocols with multiaddr (add_protocol)")
            return True
        except Exception:
            logger.debug("add_protocol present but failed; falling back to alternative registration")
            return register_webrtc_protocols_fallback()

    except Exception:
        logger.warning(
            "Could not import multiaddr protocols module or add_protocol; Using fallback registration method."
        )
        return register_webrtc_protocols_fallback()


def register_webrtc_protocols_fallback() -> None:
    """
    Fallback method to register WebRTC protocols for older multiaddr versions.
    Directly modifies the protocols table.
    """
    try:
        from multiaddr import protocols

        if hasattr(protocols, 'protocol_with_name'):
            try:
                protocols.protocol_with_name("webrtc")
                logger.debug("WebRTC protocol already registered")
                return True
            except Exception:
                pass

        Protocol = getattr(protocols, 'Protocol', None)
        if Protocol is not None:
            try:
                webrtc_proto = Protocol(code=WEBRTC_PROTOCOL_CODE, name="webrtc", size=0)
                webrtc_direct_proto = Protocol(code=WEBRTC_DIRECT_PROTOCOL_CODE, name="webrtc-direct", size=0)
            except Exception:
                Protocol = None

        if Protocol is None:
            def _make_proto(code, name):
                return type('Proto', (), {'code': code, 'name': name, 'size': 0, 'vcode': None, 'codec': None})()

            webrtc_proto = _make_proto(WEBRTC_PROTOCOL_CODE, 'webrtc')
            webrtc_direct_proto = _make_proto(WEBRTC_DIRECT_PROTOCOL_CODE, 'webrtc-direct')

        reg = getattr(protocols, 'REGISTRY', None)
        if reg is not None:
            try:
                ProtocolCls = getattr(protocols, 'Protocol', None)
                if ProtocolCls is not None:
                    try:
                        wp = ProtocolCls(code=WEBRTC_PROTOCOL_CODE, name="webrtc", size=0)
                        wpd = ProtocolCls(code=WEBRTC_DIRECT_PROTOCOL_CODE, name="webrtc-direct", size=0)
                    except Exception:
                        wp = webrtc_proto
                        wpd = webrtc_direct_proto
                else:
                    wp = webrtc_proto
                    wpd = webrtc_direct_proto

                try:
                    is_locked = getattr(reg, 'locked', False)
                except Exception:
                    is_locked = False

                target_reg = reg
                if is_locked and hasattr(reg, 'copy'):
                    try:
                        target_reg = reg.copy(unlock=True)
                    except Exception as e:
                        logger.debug(f"Could not copy/unlock REGISTRY: {e}")

                if hasattr(target_reg, 'add'):
                    try:
                        target_reg.add(wp)
                        target_reg.add(wpd)
                        if target_reg is not reg:
                            protocols.REGISTRY = target_reg

                        logger.info("Successfully registered WebRTC protocols via REGISTRY.add")
                        return True
                    except Exception as e:
                        logger.debug(f"REGISTRY.add failed: {e}")
            except Exception as e:
                logger.debug(f"Error while attempting REGISTRY registration: {e}")

        if not hasattr(protocols, 'PROTOCOLS') or not isinstance(getattr(protocols, 'PROTOCOLS', None), list):
            protocols.PROTOCOLS = []

        if not hasattr(protocols, '_names_to_protocols') or not isinstance(getattr(protocols, '_names_to_protocols', None), dict):
            protocols._names_to_protocols = {}

        if not hasattr(protocols, '_codes_to_protocols') or not isinstance(getattr(protocols, '_codes_to_protocols', None), dict):
            protocols._codes_to_protocols = {}

        # Append and update maps
        try:
            # Append to PROTOCOLS only if not already present (avoid duplicates)
            def _exists(p_list, proto):
                for p in p_list:
                    if getattr(p, 'name', None) == getattr(proto, 'name', None) or getattr(p, 'code', None) == getattr(proto, 'code', None):
                        return True
                return False

            if not _exists(protocols.PROTOCOLS, webrtc_proto):
                protocols.PROTOCOLS.append(webrtc_proto)
            if not _exists(protocols.PROTOCOLS, webrtc_direct_proto):
                protocols.PROTOCOLS.append(webrtc_direct_proto)
            name = getattr(webrtc_proto, 'name', None)
            code = getattr(webrtc_proto, 'code', None)
            if name is not None:
                protocols._names_to_protocols[name] = webrtc_proto
            if code is not None:
                protocols._codes_to_protocols[code] = webrtc_proto

            name2 = getattr(webrtc_direct_proto, 'name', None)
            code2 = getattr(webrtc_direct_proto, 'code', None)
            if name2 is not None:
                protocols._names_to_protocols[name2] = webrtc_direct_proto
            if code2 is not None:
                protocols._codes_to_protocols[code2] = webrtc_direct_proto

            # Provide protocol_with_name helper if missing
            if not hasattr(protocols, 'protocol_with_name'):
                def protocol_with_name(name: str):
                    if name in protocols._names_to_protocols:
                        return protocols._names_to_protocols[name]
                    for p in protocols.PROTOCOLS:
                        if getattr(p, 'name', None) == name:
                            return p
                    raise ValueError(f"No protocol with name '{name}' found")

                protocols.protocol_with_name = protocol_with_name

                # Also try to inform REGISTRY (so protocol_with_name which calls REGISTRY.find_by_name works)
                reg = getattr(protocols, 'REGISTRY', None)
                if reg is not None:
                    try:
                        # Try adding ProtocolCls instances to the registry if possible
                        ProtocolCls = getattr(protocols, 'Protocol', None)
                        try:
                            rp = ProtocolCls(code=getattr(webrtc_proto, 'code', WEBRTC_PROTOCOL_CODE), name=getattr(webrtc_proto, 'name', 'webrtc'), size=getattr(webrtc_proto, 'size', 0))
                            rpd = ProtocolCls(code=getattr(webrtc_direct_proto, 'code', WEBRTC_DIRECT_PROTOCOL_CODE), name=getattr(webrtc_direct_proto, 'name', 'webrtc-direct'), size=getattr(webrtc_direct_proto, 'size', 0))
                        except Exception:
                            rp = webrtc_proto
                            rpd = webrtc_direct_proto

                        if hasattr(reg, 'add'):
                            try:
                                reg.add(rp)
                                reg.add(rpd)
                            except Exception:
                                # try aliases if available
                                try:
                                    if hasattr(reg, 'add_alias_name'):
                                        reg.add_alias_name(rp, getattr(rp, 'name', None))
                                        reg.add_alias_name(rpd, getattr(rpd, 'name', None))
                                except Exception:
                                    pass
                    except Exception:
                        pass

                logger.info("Successfully registered WebRTC protocols (PROTOCOLS list fallback)")
                return True
            return True
        except Exception as e:
            logger.error(f"Fallback registration failed while updating PROTOCOLS: {e}")
            return False

    except Exception as e:
        logger.error(f"Fallback registration failed: {e}")
        return False


# Auto-register on module import
try:
    register_webrtc_protocols()
except Exception as e:
    logger.warning(f"Auto-registration of WebRTC protocols failed: {e}")
