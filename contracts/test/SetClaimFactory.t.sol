// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {SetClaimFactory} from "../src/SetClaimFactory.sol";
import {SetClaimManager} from "../src/SetClaimManager.sol";

contract SetClaimFactoryTest is Test {
    SetClaimFactory internal factory;

    address internal constant NFT_A = 0xBC4CA0Eda7647a8aB7C2061c2e118A18A936BC46; // BAYC
    address internal constant NFT_B = 0xB8Ea78fcaCEf50d41375E44E6814ebbA36Bb33c4; // Good Vibes
    bytes32 internal constant ATLAS_HASH = keccak256("atlas-v1");

    address internal backendSigner = makeAddr("backendSigner");
    address internal stranger = makeAddr("stranger");

    function setUp() public {
        factory = new SetClaimFactory();
    }

    function _tiers()
        internal
        pure
        returns (string[] memory names, uint256[] memory caps, uint256[] memory windows)
    {
        names = new string[](2);
        names[0] = "Common";
        names[1] = "Mythic";
        caps = new uint256[](2);
        caps[0] = 1000;
        caps[1] = 50;
        windows = new uint256[](2);
        windows[0] = 0;
        windows[1] = 336 hours;
    }

    function _deploy(address nft) internal returns (address) {
        (string[] memory names, uint256[] memory caps, uint256[] memory windows) = _tiers();
        return factory.deploySeason(nft, ATLAS_HASH, backendSigner, names, caps, windows);
    }

    // --- constructor ---

    function test_constructor_setsOwner() public view {
        assertEq(factory.owner(), address(this));
        assertEq(factory.seasonCount(), 0);
    }

    // --- deploySeason ---

    function test_deploySeason_deploysConfiguredManager() public {
        address manager = _deploy(NFT_A);
        assertTrue(manager != address(0));

        SetClaimManager season = SetClaimManager(manager);
        // Owned by the platform admin (factory owner), NOT the factory itself.
        assertEq(season.owner(), address(this));
        assertEq(season.nftContract(), NFT_A);
        assertEq(season.atlasHash(), ATLAS_HASH);
        assertEq(season.backendSigner(), backendSigner);
        assertEq(season.tierCount(), 2);

        (uint256 cap, uint256 windowSeconds,, bool exists) = season.tiers(keccak256("Mythic"));
        assertEq(cap, 50);
        assertEq(windowSeconds, 336 hours);
        assertTrue(exists);
    }

    function test_deploySeason_recordsAndEmits() public {
        // seasonIndex 0 is the first; manager address is created by the factory.
        vm.recordLogs();
        address manager = _deploy(NFT_A);

        assertEq(factory.seasonCount(), 1);
        assertEq(factory.seasonCountFor(NFT_A), 1);

        (address recManager, address recNft, bytes32 recAtlas, uint256 deployedAt) = factory.seasons(0);
        assertEq(recManager, manager);
        assertEq(recNft, NFT_A);
        assertEq(recAtlas, ATLAS_HASH);
        assertEq(deployedAt, block.timestamp);

        address[] memory managers = factory.seasonsFor(NFT_A);
        assertEq(managers.length, 1);
        assertEq(managers[0], manager);
        assertEq(factory.latestSeason(NFT_A), manager);
    }

    function test_deploySeason_onlyOwner() public {
        (string[] memory names, uint256[] memory caps, uint256[] memory windows) = _tiers();
        vm.prank(stranger);
        vm.expectRevert("Not owner");
        factory.deploySeason(NFT_A, ATLAS_HASH, backendSigner, names, caps, windows);
    }

    function test_deploySeason_multipleSeasonsSameContract() public {
        address s1 = _deploy(NFT_A);
        address s2 = _deploy(NFT_A);
        assertTrue(s1 != s2);

        assertEq(factory.seasonCount(), 2);
        assertEq(factory.seasonCountFor(NFT_A), 2);

        address[] memory managers = factory.seasonsFor(NFT_A);
        assertEq(managers.length, 2);
        assertEq(managers[0], s1);
        assertEq(managers[1], s2);
        assertEq(factory.latestSeason(NFT_A), s2); // newest
    }

    function test_deploySeason_separatesByContract() public {
        address a = _deploy(NFT_A);
        address b = _deploy(NFT_B);

        assertEq(factory.seasonCount(), 2);
        assertEq(factory.seasonCountFor(NFT_A), 1);
        assertEq(factory.seasonCountFor(NFT_B), 1);
        assertEq(factory.latestSeason(NFT_A), a);
        assertEq(factory.latestSeason(NFT_B), b);
    }

    function test_deploySeason_propagatesManagerConstructorReverts() public {
        // Zero-cap tier bubbles up from the SetClaimManager constructor.
        string[] memory names = new string[](1);
        names[0] = "Common";
        uint256[] memory caps = new uint256[](1);
        caps[0] = 0;
        uint256[] memory windows = new uint256[](1);
        windows[0] = 0;
        vm.expectRevert("cap=0");
        factory.deploySeason(NFT_A, ATLAS_HASH, backendSigner, names, caps, windows);
    }

    /// The deployed season is owned by the platform admin, so signer rotation works.
    function test_deployedSeason_ownerCanRotateSigner() public {
        SetClaimManager season = SetClaimManager(_deploy(NFT_A));
        address newSigner = makeAddr("newSigner");
        season.setBackendSigner(newSigner); // this test contract == factory owner == season owner
        assertEq(season.backendSigner(), newSigner);

        // A stranger cannot.
        vm.prank(stranger);
        vm.expectRevert("Not owner");
        season.setBackendSigner(stranger);
    }

    // --- views ---

    function test_latestSeason_revertsWhenNone() public {
        vm.expectRevert("No seasons");
        factory.latestSeason(NFT_A);
    }

    function test_seasonsFor_emptyWhenNone() public view {
        address[] memory managers = factory.seasonsFor(NFT_A);
        assertEq(managers.length, 0);
    }

    // --- ownership ---

    function test_transferOwnership() public {
        address newOwner = makeAddr("newOwner");

        vm.expectEmit(true, true, false, true);
        emit SetClaimFactory.OwnershipTransferred(address(this), newOwner);
        factory.transferOwnership(newOwner);
        assertEq(factory.owner(), newOwner);

        // Old owner can no longer deploy.
        (string[] memory names, uint256[] memory caps, uint256[] memory windows) = _tiers();
        vm.expectRevert("Not owner");
        factory.deploySeason(NFT_A, ATLAS_HASH, backendSigner, names, caps, windows);

        // New owner can, and the deployed season is owned by the new owner.
        vm.prank(newOwner);
        address manager = factory.deploySeason(NFT_A, ATLAS_HASH, backendSigner, names, caps, windows);
        assertEq(SetClaimManager(manager).owner(), newOwner);
    }

    function test_transferOwnership_onlyOwner() public {
        vm.prank(stranger);
        vm.expectRevert("Not owner");
        factory.transferOwnership(stranger);
    }

    function test_transferOwnership_revertsZero() public {
        vm.expectRevert("owner=0");
        factory.transferOwnership(address(0));
    }
}
