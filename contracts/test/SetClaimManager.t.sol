// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {SetClaimManager} from "../src/SetClaimManager.sol";

contract SetClaimManagerTest is Test {
    SetClaimManager internal manager;

    address internal constant NFT = 0xBC4CA0Eda7647a8aB7C2061c2e118A18A936BC46; // BAYC
    bytes32 internal constant ATLAS_HASH = keccak256("atlas-v1");

    uint256 internal backendKey;
    address internal backendSigner;
    address internal holder = makeAddr("holder");

    string internal constant COMMON = "Common";
    string internal constant MYTHIC = "Mythic";

    uint256 internal constant MYTHIC_WINDOW = 336 hours; // 14 days
    uint256 internal constant BASE_TS = 10_000_000; // sane starting timestamp (> 14-day window)

    function setUp() public {
        (backendSigner, backendKey) = makeAddrAndKey("backendSigner");
        vm.warp(BASE_TS);

        string[] memory names = new string[](2);
        names[0] = COMMON;
        names[1] = MYTHIC;
        uint256[] memory caps = new uint256[](2);
        caps[0] = 1000;
        caps[1] = 2; // small cap so "tier full" is cheap to test
        uint256[] memory windows = new uint256[](2);
        windows[0] = 0; // instant
        windows[1] = MYTHIC_WINDOW;

        manager = new SetClaimManager(address(this), NFT, ATLAS_HASH, backendSigner, names, caps, windows);
    }

    // --- helpers ---

    function _tokens(uint256 a) internal pure returns (uint256[] memory ids) {
        ids = new uint256[](1);
        ids[0] = a;
    }

    /// Backend-attest a claim. NOTE: this makes an external (static) call to
    /// `claimDigest`, so it MUST be invoked before any `vm.expectRevert`/`vm.prank`
    /// that targets the subsequent `claim` — those cheat codes arm only the next call.
    function _sign(
        uint256 key,
        address wallet,
        string memory tier,
        uint256[] memory tokenIds,
        uint256 windowStartedAt,
        uint256 expiry,
        uint256 nonce
    ) internal view returns (bytes memory) {
        bytes32 digest = manager.claimDigest(wallet, tier, tokenIds, windowStartedAt, expiry, nonce);
        bytes32 ethHash = keccak256(abi.encodePacked("\x19Ethereum Signed Message:\n32", digest));
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(key, ethHash);
        return abi.encodePacked(r, s, v);
    }

    // --- constructor ---

    function test_constructor_setsState() public view {
        assertEq(manager.nftContract(), NFT);
        assertEq(manager.atlasHash(), ATLAS_HASH);
        assertEq(manager.owner(), address(this));
        assertEq(manager.backendSigner(), backendSigner);
        assertEq(manager.tierCount(), 2);

        (uint256 cap, uint256 windowSeconds, uint256 claimed, bool exists) =
            manager.tiers(keccak256(bytes(COMMON)));
        assertEq(cap, 1000);
        assertEq(windowSeconds, 0);
        assertEq(claimed, 0);
        assertTrue(exists);
    }

    function _deploy(
        address nft,
        address signer,
        string[] memory names,
        uint256[] memory caps,
        uint256[] memory windows
    ) internal returns (SetClaimManager) {
        return new SetClaimManager(address(this), nft, ATLAS_HASH, signer, names, caps, windows);
    }

    function test_constructor_revertsZeroOwner() public {
        string[] memory names = new string[](1);
        names[0] = COMMON;
        uint256[] memory caps = new uint256[](1);
        caps[0] = 1;
        uint256[] memory windows = new uint256[](1);
        windows[0] = 0;
        vm.expectRevert("owner=0");
        new SetClaimManager(address(0), NFT, ATLAS_HASH, backendSigner, names, caps, windows);
    }

    function test_constructor_revertsZeroNft() public {
        string[] memory names = new string[](1);
        names[0] = COMMON;
        uint256[] memory caps = new uint256[](1);
        caps[0] = 1;
        uint256[] memory windows = new uint256[](1);
        windows[0] = 0;
        vm.expectRevert("nftContract=0");
        _deploy(address(0), backendSigner, names, caps, windows);
    }

    function test_constructor_revertsZeroSigner() public {
        string[] memory names = new string[](1);
        names[0] = COMMON;
        uint256[] memory caps = new uint256[](1);
        caps[0] = 1;
        uint256[] memory windows = new uint256[](1);
        windows[0] = 0;
        vm.expectRevert("backendSigner=0");
        _deploy(NFT, address(0), names, caps, windows);
    }

    function test_constructor_revertsNoTiers() public {
        string[] memory names = new string[](0);
        uint256[] memory caps = new uint256[](0);
        uint256[] memory windows = new uint256[](0);
        vm.expectRevert("no tiers");
        _deploy(NFT, backendSigner, names, caps, windows);
    }

    function test_constructor_revertsArityMismatch() public {
        string[] memory names = new string[](2);
        names[0] = COMMON;
        names[1] = MYTHIC;
        uint256[] memory caps = new uint256[](1); // wrong length
        caps[0] = 1;
        uint256[] memory windows = new uint256[](2);
        vm.expectRevert("tier arity mismatch");
        _deploy(NFT, backendSigner, names, caps, windows);
    }

    function test_constructor_revertsEmptyTierName() public {
        string[] memory names = new string[](1);
        names[0] = "";
        uint256[] memory caps = new uint256[](1);
        caps[0] = 1;
        uint256[] memory windows = new uint256[](1);
        windows[0] = 0;
        vm.expectRevert("empty tier name");
        _deploy(NFT, backendSigner, names, caps, windows);
    }

    function test_constructor_revertsZeroCap() public {
        string[] memory names = new string[](1);
        names[0] = COMMON;
        uint256[] memory caps = new uint256[](1);
        caps[0] = 0;
        uint256[] memory windows = new uint256[](1);
        windows[0] = 0;
        vm.expectRevert("cap=0");
        _deploy(NFT, backendSigner, names, caps, windows);
    }

    function test_constructor_revertsDuplicateTier() public {
        string[] memory names = new string[](2);
        names[0] = COMMON;
        names[1] = COMMON;
        uint256[] memory caps = new uint256[](2);
        caps[0] = 1;
        caps[1] = 1;
        uint256[] memory windows = new uint256[](2);
        vm.expectRevert("duplicate tier");
        _deploy(NFT, backendSigner, names, caps, windows);
    }

    // --- claim happy path ---

    function test_claim_emitsAndAwardsSlot() public {
        uint256[] memory ids = _tokens(42);
        uint256 windowStartedAt = BASE_TS - 1 hours;
        uint256 expiry = BASE_TS + 1 hours;
        uint256 nonce = 1;
        bytes memory sig = _sign(backendKey, holder, COMMON, ids, windowStartedAt, expiry, nonce);

        vm.expectEmit(true, true, true, true);
        emit SetClaimManager.Claimed(
            keccak256(bytes(COMMON)), COMMON, holder, 1, ids, nonce, windowStartedAt
        );

        vm.prank(holder);
        manager.claim(COMMON, ids, windowStartedAt, expiry, nonce, sig);

        (,, uint256 claimed,) = manager.tiers(keccak256(bytes(COMMON)));
        assertEq(claimed, 1);
        assertTrue(manager.nonceUsed(nonce));
        assertEq(manager.slotsRemaining(COMMON), 999);
    }

    function test_claim_holdingWindowElapsed() public {
        uint256[] memory ids = _tokens(7);
        uint256 windowStartedAt = BASE_TS - MYTHIC_WINDOW; // exactly elapsed
        uint256 expiry = BASE_TS + 1 hours;
        bytes memory sig = _sign(backendKey, holder, MYTHIC, ids, windowStartedAt, expiry, 5);

        vm.prank(holder);
        manager.claim(MYTHIC, ids, windowStartedAt, expiry, 5, sig);
        (,, uint256 claimed,) = manager.tiers(keccak256(bytes(MYTHIC)));
        assertEq(claimed, 1);
    }

    /// No per-wallet cap: the same wallet may take multiple slots in one tier
    /// (different nonces / signatures). This is the resolved "whales may sweep" rule.
    function test_claim_sameWalletMultipleSlots() public {
        uint256 expiry = BASE_TS + 1 hours;
        uint256[] memory ids1 = _tokens(1);
        uint256[] memory ids2 = _tokens(2);
        bytes memory sig1 = _sign(backendKey, holder, MYTHIC, ids1, BASE_TS - MYTHIC_WINDOW, expiry, 10);
        bytes memory sig2 = _sign(backendKey, holder, MYTHIC, ids2, BASE_TS - MYTHIC_WINDOW, expiry, 11);

        vm.prank(holder);
        manager.claim(MYTHIC, ids1, BASE_TS - MYTHIC_WINDOW, expiry, 10, sig1);
        vm.prank(holder);
        manager.claim(MYTHIC, ids2, BASE_TS - MYTHIC_WINDOW, expiry, 11, sig2);

        (,, uint256 claimed,) = manager.tiers(keccak256(bytes(MYTHIC)));
        assertEq(claimed, 2);
        assertEq(manager.slotsRemaining(MYTHIC), 0); // cap 2 now full
    }

    // --- claim reverts ---

    function test_claim_revertsUnknownTier() public {
        uint256[] memory ids = _tokens(1);
        uint256 expiry = BASE_TS + 1 hours;
        bytes memory sig = _sign(backendKey, holder, "Nope", ids, BASE_TS - 1, expiry, 1);
        vm.prank(holder);
        vm.expectRevert("Unknown tier");
        manager.claim("Nope", ids, BASE_TS - 1, expiry, 1, sig);
    }

    function test_claim_revertsExpired() public {
        uint256[] memory ids = _tokens(1);
        uint256 expiry = BASE_TS - 1; // already past
        bytes memory sig = _sign(backendKey, holder, COMMON, ids, BASE_TS - 1, expiry, 1);
        vm.prank(holder);
        vm.expectRevert("Signature expired");
        manager.claim(COMMON, ids, BASE_TS - 1, expiry, 1, sig);
    }

    function test_claim_revertsNonceReuse() public {
        uint256[] memory ids = _tokens(1);
        uint256 expiry = BASE_TS + 1 hours;
        bytes memory sig = _sign(backendKey, holder, COMMON, ids, BASE_TS - 1, expiry, 99);

        vm.prank(holder);
        manager.claim(COMMON, ids, BASE_TS - 1, expiry, 99, sig);

        // Replaying the identical signed claim fails on the used nonce.
        vm.prank(holder);
        vm.expectRevert("Nonce used");
        manager.claim(COMMON, ids, BASE_TS - 1, expiry, 99, sig);
    }

    function test_claim_revertsTierFull() public {
        uint256 expiry = BASE_TS + 1 hours;
        uint256 ws = BASE_TS - MYTHIC_WINDOW;
        // Fill the cap-2 Mythic tier.
        bytes memory s1 = _sign(backendKey, holder, MYTHIC, _tokens(1), ws, expiry, 1);
        bytes memory s2 = _sign(backendKey, holder, MYTHIC, _tokens(2), ws, expiry, 2);
        bytes memory s3 = _sign(backendKey, holder, MYTHIC, _tokens(3), ws, expiry, 3);
        vm.prank(holder);
        manager.claim(MYTHIC, _tokens(1), ws, expiry, 1, s1);
        vm.prank(holder);
        manager.claim(MYTHIC, _tokens(2), ws, expiry, 2, s2);

        vm.prank(holder);
        vm.expectRevert("Tier full");
        manager.claim(MYTHIC, _tokens(3), ws, expiry, 3, s3);
    }

    function test_claim_revertsNoTokens() public {
        uint256[] memory empty = new uint256[](0);
        uint256 expiry = BASE_TS + 1 hours;
        bytes memory sig = _sign(backendKey, holder, COMMON, empty, BASE_TS - 1, expiry, 1);
        vm.prank(holder);
        vm.expectRevert("No tokens");
        manager.claim(COMMON, empty, BASE_TS - 1, expiry, 1, sig);
    }

    function test_claim_revertsNoWindowStart() public {
        uint256[] memory ids = _tokens(1);
        uint256 expiry = BASE_TS + 1 hours;
        bytes memory sig = _sign(backendKey, holder, COMMON, ids, 0, expiry, 1);
        vm.prank(holder);
        vm.expectRevert("No window start");
        manager.claim(COMMON, ids, 0, expiry, 1, sig);
    }

    function test_claim_revertsWindowNotElapsed() public {
        uint256[] memory ids = _tokens(1);
        uint256 windowStartedAt = BASE_TS - (MYTHIC_WINDOW - 1); // 1s short
        uint256 expiry = BASE_TS + 1 hours;
        bytes memory sig = _sign(backendKey, holder, MYTHIC, ids, windowStartedAt, expiry, 1);
        vm.prank(holder);
        vm.expectRevert("Window not elapsed");
        manager.claim(MYTHIC, ids, windowStartedAt, expiry, 1, sig);
    }

    function test_claim_revertsWrongSigner() public {
        (, uint256 attackerKey) = makeAddrAndKey("attacker");
        uint256[] memory ids = _tokens(1);
        uint256 expiry = BASE_TS + 1 hours;
        bytes memory forged = _sign(attackerKey, holder, COMMON, ids, BASE_TS - 1, expiry, 1);
        vm.prank(holder);
        vm.expectRevert("Unauthorized: bad backend signature");
        manager.claim(COMMON, ids, BASE_TS - 1, expiry, 1, forged);
    }

    function test_claim_revertsTamperedTokenIds() public {
        uint256[] memory signed = _tokens(1);
        uint256[] memory submitted = _tokens(999); // different set than signed
        uint256 expiry = BASE_TS + 1 hours;
        bytes memory sig = _sign(backendKey, holder, COMMON, signed, BASE_TS - 1, expiry, 1);
        vm.prank(holder);
        vm.expectRevert("Unauthorized: bad backend signature");
        manager.claim(COMMON, submitted, BASE_TS - 1, expiry, 1, sig);
    }

    function test_claim_revertsWrongWallet() public {
        // Attestation was issued for `holder`; a different wallet can't use it.
        address attacker = makeAddr("otherWallet");
        uint256[] memory ids = _tokens(1);
        uint256 expiry = BASE_TS + 1 hours;
        bytes memory sig = _sign(backendKey, holder, COMMON, ids, BASE_TS - 1, expiry, 1);
        vm.prank(attacker);
        vm.expectRevert("Unauthorized: bad backend signature");
        manager.claim(COMMON, ids, BASE_TS - 1, expiry, 1, sig);
    }

    function test_claim_revertsBadSigLength() public {
        uint256[] memory ids = _tokens(1);
        uint256 expiry = BASE_TS + 1 hours;
        vm.prank(holder);
        vm.expectRevert("Bad sig length");
        manager.claim(COMMON, ids, BASE_TS - 1, expiry, 1, hex"1234");
    }

    function test_claim_revertsCrossChainReplay() public {
        uint256[] memory ids = _tokens(1);
        uint256 expiry = BASE_TS + 1 hours;
        bytes memory sig = _sign(backendKey, holder, COMMON, ids, BASE_TS - 1, expiry, 1);
        vm.chainId(block.chainid + 1); // digest was bound to the original chainId
        vm.prank(holder);
        vm.expectRevert("Unauthorized: bad backend signature");
        manager.claim(COMMON, ids, BASE_TS - 1, expiry, 1, sig);
    }

    function test_claim_revertsCrossSeasonReplay() public {
        // A signature for this season can't be replayed on a different SetClaimManager
        // (the digest binds address(this)).
        uint256[] memory ids = _tokens(1);
        uint256 expiry = BASE_TS + 1 hours;
        bytes memory sig = _sign(backendKey, holder, COMMON, ids, BASE_TS - 1, expiry, 1);

        string[] memory names = new string[](1);
        names[0] = COMMON;
        uint256[] memory caps = new uint256[](1);
        caps[0] = 10;
        uint256[] memory windows = new uint256[](1);
        windows[0] = 0;
        SetClaimManager other = _deploy(NFT, backendSigner, names, caps, windows);

        vm.prank(holder);
        vm.expectRevert("Unauthorized: bad backend signature");
        other.claim(COMMON, ids, BASE_TS - 1, expiry, 1, sig);
    }

    // --- signer rotation ---

    function test_claim_succeedsAfterSignerRotation() public {
        (address newSigner, uint256 newKey) = makeAddrAndKey("newBackendSigner");
        manager.setBackendSigner(newSigner);
        assertEq(manager.backendSigner(), newSigner);

        uint256[] memory ids = _tokens(1);
        uint256 expiry = BASE_TS + 1 hours;

        // Old signer no longer works.
        bytes memory oldSig = _sign(backendKey, holder, COMMON, ids, BASE_TS - 1, expiry, 1);
        vm.prank(holder);
        vm.expectRevert("Unauthorized: bad backend signature");
        manager.claim(COMMON, ids, BASE_TS - 1, expiry, 1, oldSig);

        // New signer does.
        bytes memory newSig = _sign(newKey, holder, COMMON, ids, BASE_TS - 1, expiry, 1);
        vm.prank(holder);
        manager.claim(COMMON, ids, BASE_TS - 1, expiry, 1, newSig);
        assertTrue(manager.nonceUsed(1));
    }

    function test_setBackendSigner_onlyOwner() public {
        vm.prank(holder);
        vm.expectRevert("Not owner");
        manager.setBackendSigner(holder);
    }

    function test_setBackendSigner_revertsZero() public {
        vm.expectRevert("backendSigner=0");
        manager.setBackendSigner(address(0));
    }
}
