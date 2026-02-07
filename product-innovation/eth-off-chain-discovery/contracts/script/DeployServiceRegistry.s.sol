// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Script} from "forge-std/Script.sol";
import {ServiceRegistry} from "../src/ServiceRegistry.sol";

contract DeployServiceRegistry is Script {
    function run() external returns (ServiceRegistry) {
        vm.startBroadcast();
        ServiceRegistry registry = new ServiceRegistry();
        vm.stopBroadcast();

        string memory contractAddress = vm.toString(address(registry));
        vm.writeJson(
            contractAddress,
            "../deploy_output.json",
            ".contract_address"
        );

        string memory abiPath = string.concat(
            vm.projectRoot(),
            "/out/ServiceRegistry.sol/ServiceRegistry.json"
        );
        string memory contractABI = vm.readFile(abiPath);
        vm.writeJson(contractABI, "../deploy_output.json", ".abi");

        return registry;
    }
}
