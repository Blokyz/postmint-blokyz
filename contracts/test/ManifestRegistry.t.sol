// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {ManifestRegistry} from "../src/ManifestRegistry.sol";

contract ManifestRegistryTest is Test {
    ManifestRegistry internal registry;
    address internal constant BAYC = 0xBC4CA0Eda7647a8aB7C2061c2e118A18A936BC46;

    bytes32 internal constant RANKING_HASH = keccak256("ranking-v1");
    bytes32 internal constant ATLAS_HASH = keccak256("atlas-v1");

    uint256 internal backendKey;
    address internal backendSigner;
    address internal projectOwner = makeAddr("projectOwner");

    function setUp() public {
        (backendSigner, backendKey) = makeAddrAndKey("backendSigner");
        registry = new ManifestRegistry(backendSigner);
    }

    /// Produce a valid backend attestation for the given lock data.
    function _attest(address nft, bytes32 ranking, bytes32 atlas) internal view returns (bytes memory) {
        bytes32 digest = registry.lockDigest(nft, ranking, atlas);
        bytes32 ethHash = keccak256(abi.encodePacked("\x19Ethereum Signed Message:\n32", digest));
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(backendKey, ethHash);
        return abi.encodePacked(r, s, v);
    }

    function test_constructor_setsSignerAndOwner() public view {
        assertEq(registry.owner(), address(this));
        assertEq(registry.backendSigner(), backendSigner);
    }

    function test_constructor_revertsZeroSigner() public {
        vm.expectRevert("backendSigner=0");
        new ManifestRegistry(address(0));
    }

    function test_lockManifest_emitsAndStores() public {
        bytes memory sig = _attest(BAYC, RANKING_HASH, ATLAS_HASH);

        vm.expectEmit(true, true, true, true);
        emit ManifestRegistry.ManifestLocked(BAYC, RANKING_HASH, ATLAS_HASH, projectOwner);

        vm.prank(projectOwner);
        registry.lockManifest(BAYC, RANKING_HASH, ATLAS_HASH, sig);

        (bytes32 ranking, bytes32 atlas, address approver, uint256 approvedAt, bool locked) =
            registry.manifests(BAYC);
        assertEq(ranking, RANKING_HASH);
        assertEq(atlas, ATLAS_HASH);
        assertEq(approver, projectOwner); // submitter is recorded, not the backend
        assertGt(approvedAt, 0);
        assertTrue(locked);
    }

    function test_verifyAtlas() public {
        registry.lockManifest(BAYC, RANKING_HASH, ATLAS_HASH, _attest(BAYC, RANKING_HASH, ATLAS_HASH));
        assertTrue(registry.verifyAtlas(BAYC, ATLAS_HASH));
        assertFalse(registry.verifyAtlas(BAYC, bytes32(uint256(1))));
    }

    function test_lockManifest_revertsIfAlreadyLocked() public {
        bytes memory sig = _attest(BAYC, RANKING_HASH, ATLAS_HASH);
        registry.lockManifest(BAYC, RANKING_HASH, ATLAS_HASH, sig);
        vm.expectRevert("Already locked");
        registry.lockManifest(BAYC, RANKING_HASH, ATLAS_HASH, sig);
    }

    function test_lockManifest_revertsZeroAddress() public {
        bytes memory sig = _attest(address(0), RANKING_HASH, ATLAS_HASH);
        vm.expectRevert("Invalid contract");
        registry.lockManifest(address(0), RANKING_HASH, ATLAS_HASH, sig);
    }

    // --- access control ---

    function test_lockManifest_revertsOnWrongSigner() public {
        (, uint256 attackerKey) = makeAddrAndKey("attacker");
        bytes32 digest = registry.lockDigest(BAYC, RANKING_HASH, ATLAS_HASH);
        bytes32 ethHash = keccak256(abi.encodePacked("\x19Ethereum Signed Message:\n32", digest));
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(attackerKey, ethHash);
        bytes memory forged = abi.encodePacked(r, s, v);

        vm.expectRevert("Unauthorized: bad backend signature");
        registry.lockManifest(BAYC, RANKING_HASH, ATLAS_HASH, forged);
    }

    function test_lockManifest_revertsOnTamperedHash() public {
        // Valid sig for ATLAS_HASH, but caller submits a different atlas hash.
        bytes memory sig = _attest(BAYC, RANKING_HASH, ATLAS_HASH);
        vm.expectRevert("Unauthorized: bad backend signature");
        registry.lockManifest(BAYC, RANKING_HASH, keccak256("atlas-tampered"), sig);
    }

    function test_lockManifest_revertsOnWrongContract() public {
        // Attestation bound to BAYC can't be replayed onto another collection.
        bytes memory sig = _attest(BAYC, RANKING_HASH, ATLAS_HASH);
        address other = makeAddr("otherCollection");
        vm.expectRevert("Unauthorized: bad backend signature");
        registry.lockManifest(other, RANKING_HASH, ATLAS_HASH, sig);
    }

    function test_lockManifest_revertsOnReplayDifferentChain() public {
        bytes memory sig = _attest(BAYC, RANKING_HASH, ATLAS_HASH);
        vm.chainId(block.chainid + 1); // attestation was bound to the original chainId
        vm.expectRevert("Unauthorized: bad backend signature");
        registry.lockManifest(BAYC, RANKING_HASH, ATLAS_HASH, sig);
    }

    function test_lockManifest_revertsOnBadSigLength() public {
        vm.expectRevert("Bad sig length");
        registry.lockManifest(BAYC, RANKING_HASH, ATLAS_HASH, hex"1234");
    }

    function test_lockManifest_succeedsAfterSignerRotation() public {
        (address newSigner, uint256 newKey) = makeAddrAndKey("newBackendSigner");
        registry.setBackendSigner(newSigner);
        assertEq(registry.backendSigner(), newSigner);

        // Old signer no longer works.
        bytes memory oldSig = _attest(BAYC, RANKING_HASH, ATLAS_HASH);
        vm.expectRevert("Unauthorized: bad backend signature");
        registry.lockManifest(BAYC, RANKING_HASH, ATLAS_HASH, oldSig);

        // New signer does.
        bytes32 ethHash = keccak256(
            abi.encodePacked(
                "\x19Ethereum Signed Message:\n32", registry.lockDigest(BAYC, RANKING_HASH, ATLAS_HASH)
            )
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(newKey, ethHash);
        registry.lockManifest(BAYC, RANKING_HASH, ATLAS_HASH, abi.encodePacked(r, s, v));
        assertTrue(registry.isLocked(BAYC));
    }

    function test_setBackendSigner_onlyOwner() public {
        vm.prank(projectOwner);
        vm.expectRevert("Not owner");
        registry.setBackendSigner(projectOwner);
    }

    function test_setBackendSigner_revertsZero() public {
        vm.expectRevert("backendSigner=0");
        registry.setBackendSigner(address(0));
    }
}
