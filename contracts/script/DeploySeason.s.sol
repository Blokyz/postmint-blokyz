// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script} from "forge-std/Script.sol";
import {console} from "forge-std/console.sol";
import {SetClaimFactory} from "../src/SetClaimFactory.sol";

/// @notice Deploy a season (`SetClaimManager`) for a collection through the
///         factory. Caps + windows are frozen at construction, so they must
///         mirror the collection's tuned atlas `tier_structure` exactly
///         (positionally aligned, windows in SECONDS).
///
/// Env:
///   DEPLOYER_PRIVATE_KEY     factory owner key (deploySeason is owner-gated)
///   CLAIM_FACTORY_ADDRESS    deployed SetClaimFactory
///   SEASON_NFT_CONTRACT      collection the season races over
///   SEASON_ATLAS_HASH        locked atlas-manifest hash (bytes32)
///   BACKEND_SIGNER_ADDRESS   trusted claim-attestation signer
///   SEASON_TIER_NAMES        comma-separated, e.g. "Common,Uncommon,Rare,Super Rare,Mythic"
///   SEASON_TIER_CAPS         comma-separated uints, positionally aligned
///   SEASON_TIER_WINDOWS      comma-separated uints (seconds), positionally aligned
///
/// forge script script/DeploySeason.s.sol:DeploySeason \
///   --rpc-url base_sepolia --broadcast
/// After deploying, register the season with the backend:
///   POST /claims/season {contract_address, manager_address, atlas_hash}
contract DeploySeason is Script {
    function run() external returns (address manager) {
        uint256 deployerKey = vm.envUint("DEPLOYER_PRIVATE_KEY");
        SetClaimFactory factory = SetClaimFactory(vm.envAddress("CLAIM_FACTORY_ADDRESS"));
        address nftContract = vm.envAddress("SEASON_NFT_CONTRACT");
        bytes32 atlasHash = vm.envBytes32("SEASON_ATLAS_HASH");
        address backendSigner = vm.envAddress("BACKEND_SIGNER_ADDRESS");
        string[] memory tierNames = vm.envString("SEASON_TIER_NAMES", ",");
        uint256[] memory caps = vm.envUint("SEASON_TIER_CAPS", ",");
        uint256[] memory windows = vm.envUint("SEASON_TIER_WINDOWS", ",");

        require(tierNames.length == caps.length && caps.length == windows.length, "tier arity mismatch");

        vm.startBroadcast(deployerKey);
        manager = factory.deploySeason(nftContract, atlasHash, backendSigner, tierNames, caps, windows);
        vm.stopBroadcast();

        console.log("Season (SetClaimManager) deployed at:", manager);
        console.log("nftContract:", nftContract);
        console.log("backendSigner:", backendSigner);
        for (uint256 i = 0; i < tierNames.length; i++) {
            console.log(tierNames[i], "cap:", caps[i]);
        }
    }
}
