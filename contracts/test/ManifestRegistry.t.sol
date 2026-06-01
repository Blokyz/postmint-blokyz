// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {ManifestRegistry} from "../src/ManifestRegistry.sol";

contract ManifestRegistryTest is Test {
    ManifestRegistry internal registry;
    address internal constant BAYC = 0xBC4CA0EdA7647A8aB7C2061c2E118A18a936bC46;

    bytes32 internal constant RANKING_HASH = keccak256("ranking-v1");
    bytes32 internal constant ATLAS_HASH = keccak256("atlas-v1");

    function setUp() public {
        registry = new ManifestRegistry();
    }

    function test_lockManifest_emitsAndStores() public {
        vm.expectEmit(true, true, true, true);
        emit ManifestRegistry.ManifestLocked(BAYC, RANKING_HASH, ATLAS_HASH, address(this));

        registry.lockManifest(BAYC, RANKING_HASH, ATLAS_HASH);

        (bytes32 ranking, bytes32 atlas, address approver, uint256 approvedAt, bool locked) =
            registry.manifests(BAYC);
        assertEq(ranking, RANKING_HASH);
        assertEq(atlas, ATLAS_HASH);
        assertEq(approver, address(this));
        assertGt(approvedAt, 0);
        assertTrue(locked);
    }

    function test_verifyAtlas() public {
        registry.lockManifest(BAYC, RANKING_HASH, ATLAS_HASH);
        assertTrue(registry.verifyAtlas(BAYC, ATLAS_HASH));
        assertFalse(registry.verifyAtlas(BAYC, bytes32(uint256(1))));
    }

    function test_lockManifest_revertsIfAlreadyLocked() public {
        registry.lockManifest(BAYC, RANKING_HASH, ATLAS_HASH);
        vm.expectRevert("Already locked");
        registry.lockManifest(BAYC, RANKING_HASH, ATLAS_HASH);
    }

    function test_lockManifest_revertsZeroAddress() public {
        vm.expectRevert("Invalid contract");
        registry.lockManifest(address(0), RANKING_HASH, ATLAS_HASH);
    }
}
