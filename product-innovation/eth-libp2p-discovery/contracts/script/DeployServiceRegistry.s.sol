// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Script} from "forge-std/Script.sol";
import {ServiceRegistry} from "../src/ServiceRegistry.sol";

contract DeployServiceRegistry is Script {
    function run() external returns (ServiceRegistry) {
        vm.startBroadcast();
        ServiceRegistry registry = new ServiceRegistry();
        vm.stopBroadcast();
        return registry;
    }
}
