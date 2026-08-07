// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script} from "forge-std/Script.sol";
import {console} from "forge-std/console.sol";
import {SetClaimFactory} from "../src/SetClaimFactory.sol";

/// @notice Deploy the SetClaimFactory (platform season registry). The broadcast
///         sender becomes the factory owner — the only address that may deploy
///         seasons — so use the platform admin key.
/// forge script script/DeploySetClaimFactory.s.sol:DeploySetClaimFactory \
///   --rpc-url base_sepolia --broadcast
contract DeploySetClaimFactory is Script {
    function run() external returns (address deployed) {
        uint256 deployerKey = vm.envUint("DEPLOYER_PRIVATE_KEY");
        vm.startBroadcast(deployerKey);
        deployed = address(new SetClaimFactory());
        vm.stopBroadcast();
        console.log("SetClaimFactory deployed at:", deployed);
        console.log("owner:", vm.addr(deployerKey));
    }
}
