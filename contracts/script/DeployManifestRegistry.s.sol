// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script} from "forge-std/Script.sol";
import {ManifestRegistry} from "../src/ManifestRegistry.sol";

/// @notice Deploy ManifestRegistry to Base Sepolia.
/// forge script script/DeployManifestRegistry.s.sol:DeployManifestRegistry \
///   --rpc-url base_sepolia --broadcast
contract DeployManifestRegistry is Script {
    function run() external returns (address deployed) {
        uint256 deployerKey = vm.envUint("DEPLOYER_PRIVATE_KEY");
        vm.startBroadcast(deployerKey);
        deployed = address(new ManifestRegistry());
        vm.stopBroadcast();
        console.log("ManifestRegistry deployed at:", deployed);
    }
}
