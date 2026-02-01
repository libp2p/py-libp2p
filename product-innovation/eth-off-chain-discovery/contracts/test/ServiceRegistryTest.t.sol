// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {ServiceRegistry} from "../src/ServiceRegistry.sol";
import {DeployServiceRegistry} from "../script/DeployServiceRegistry.s.sol";

contract ServiceRegistryTest is Test {
    ServiceRegistry registry;
    DeployServiceRegistry deployer;

    address alice = address(0xBEEF);
    address bob = address(0xCAFE);

    bytes32 serviceId = keccak256("dex:uniswap:v1");
    bytes pointer1 = abi.encodePacked(uint8(42), bytes20(address(0xABCD)));
    bytes pointer2 = abi.encodePacked(uint8(99), bytes20(address(0xDEAD)));

    function setUp() external {
        deployer = new DeployServiceRegistry();
        registry = deployer.run();
    }

    function testRegisterService_setsOwnerAndEmitsEvent() public {
        vm.prank(alice);
        vm.expectEmit(true, true, false, false);
        emit ServiceRegistry.ServiceRegistered(serviceId, alice);

        registry.registerService(serviceId);

        assertEq(registry.getServiceOwner(serviceId), alice, "service owner mismatch");
    }

    function testRegisterService_revertsIfRegistered() public {
        vm.prank(alice);
        registry.registerService(serviceId);

        vm.prank(bob);
        vm.expectRevert("service already registered");
        registry.registerService(serviceId);
    }

    function testSetPointer_asOwner_setsPointerAndEmitsEvent() public {
        vm.prank(alice);
        registry.registerService(serviceId);

        vm.prank(alice);
        vm.expectEmit(true, false, false, true);
        emit ServiceRegistry.ServicePointerUpdated(serviceId, pointer1);

        registry.setServicePointer(serviceId, pointer1);

        bytes memory stored = registry.getServicePointer(serviceId);
        assertEq(stored, pointer1, "pointer mismatch");
    }

    function testSetPointer_nonOwnerRevert() public {
        vm.prank(alice);
        registry.registerService(serviceId);

        vm.prank(bob);
        vm.expectRevert("not service owner");
        registry.setServicePointer(serviceId, pointer1);
    }

    function testGetServiceOwner_unregistered_returnsZero() public view {
        assertEq(registry.getServiceOwner(keccak256("some:unregistered")), address(0));
    }

    function testSetPointer_multipleUpdates() public {
        vm.prank(alice);
        registry.registerService(serviceId);

        vm.prank(alice);
        registry.setServicePointer(serviceId, pointer1);
        assertEq(registry.getServicePointer(serviceId), pointer1);

        vm.prank(alice);
        registry.setServicePointer(serviceId, pointer2);
        assertEq(registry.getServicePointer(serviceId), pointer2);
    }
}
