// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title ServiceRegistry
/// @notice On-chain authority that anchors off-chain service discovery
contract ServiceRegistry {
    struct Service {
        address owner;
        bytes pointer;
    }

    mapping(bytes32 => Service) private services;

    event ServiceRegistered(bytes32 indexed serviceId, address indexed owner);
    event ServicePointerUpdated(bytes32 indexed serviceId, bytes pointer);

    /// @notice Register a new service ID
    /// @param serviceId Deterministic identifier (e.g. keccak256("dex:uniswap:v1"))
    function registerService(bytes32 serviceId) external {
        require(services[serviceId].owner == address(0), "service already registered");

        services[serviceId].owner = msg.sender;
        emit ServiceRegistered(serviceId, msg.sender);
    }

    /// @notice Update the off-chain discovery pointer for a service
    /// @param serviceId Service identifier
    /// @param pointer CID / DHT key / libp2p PeerID
    function setServicePointer(bytes32 serviceId, bytes calldata pointer) external {
        require(services[serviceId].owner == msg.sender, "not service owner");

        services[serviceId].pointer = pointer;
        emit ServicePointerUpdated(serviceId, pointer);
    }

    /// @notice Get the service owner
    function getServiceOwner(bytes32 serviceId) external view returns (address) {
        return services[serviceId].owner;
    }

    /// @notice Get the off-chain discovery pointer
    function getServicePointer(bytes32 serviceId) external view returns (bytes memory) {
        return services[serviceId].pointer;
    }
}
