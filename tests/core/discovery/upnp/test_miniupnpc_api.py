import miniupnpc


def test_miniupnpc_api_surface() -> None:
    gateway = miniupnpc.UPnP()

    required_methods = (
        "discover",
        "selectigd",
        "externalipaddress",
        "connectiontype",
        "addportmapping",
        "deleteportmapping",
    )
    for method_name in required_methods:
        assert hasattr(gateway, method_name), f"UPnP missing method: {method_name}"
        assert callable(getattr(gateway, method_name)), (
            f"UPnP attribute is not callable: {method_name}"
        )

    assert hasattr(gateway, "lanaddr"), "UPnP missing attribute: lanaddr"
    lanaddr = gateway.lanaddr
    assert lanaddr is None or isinstance(lanaddr, str)
