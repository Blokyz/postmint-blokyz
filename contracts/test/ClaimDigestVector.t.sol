// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test, console} from "forge-std/Test.sol";
import {SetClaimManager} from "../src/SetClaimManager.sol";

/// @notice Emits golden `claimDigest` vectors from the real contract so the Python
///         mirror (`app/claim_signing.build_claim_digest`) can be cross-checked
///         byte-for-byte. Run: `forge test --match-contract ClaimDigestVector -vv`.
///         The deployed manager address is deterministic (CREATE from this test
///         contract at a fixed nonce), so the printed values are reproducible.
contract ClaimDigestVectorTest is Test {
    address internal constant NFT = 0xBC4CA0Eda7647a8aB7C2061c2e118A18A936BC46; // BAYC
    address internal constant WALLET = 0x1111111111111111111111111111111111111111;
    bytes32 internal constant ATLAS_HASH = keccak256("atlas-v1");
    uint256 internal constant CHAIN_ID = 84532; // Base Sepolia

    function _deploy() internal returns (SetClaimManager) {
        string[] memory names = new string[](2);
        names[0] = "Common";
        names[1] = "Mythic";
        uint256[] memory caps = new uint256[](2);
        caps[0] = 1000;
        caps[1] = 50;
        uint256[] memory windows = new uint256[](2);
        windows[0] = 0;
        windows[1] = 336 hours;
        // signer/owner irrelevant to the digest; any non-zero value works.
        return new SetClaimManager(address(uint160(1)), NFT, ATLAS_HASH, address(uint160(1)), names, caps, windows);
    }

    function test_emitVectors() public {
        vm.chainId(CHAIN_ID);
        SetClaimManager m = _deploy();
        console.log("chainId       :", CHAIN_ID);
        console.log("managerAddress:", address(m));
        console.log("nftContract   :", NFT);
        console.log("wallet        :", WALLET);

        // Vector 1: 3 tokens, "Mythic"
        uint256[] memory ids3 = new uint256[](3);
        ids3[0] = 1;
        ids3[1] = 2;
        ids3[2] = 3;
        console.log("--- vector1: tier=Mythic ids=[1,2,3] ws=1000000 exp=1003600 nonce=7");
        console.logBytes32(m.claimDigest(WALLET, "Mythic", ids3, 1_000_000, 1_003_600, 7));

        // Vector 2: 1 token, "Common"
        uint256[] memory ids1 = new uint256[](1);
        ids1[0] = 8888;
        console.log("--- vector2: tier=Common ids=[8888] ws=1700000000 exp=1700003600 nonce=42");
        console.logBytes32(m.claimDigest(WALLET, "Common", ids1, 1_700_000_000, 1_700_003_600, 42));

        // Vector 3: large token id (full-width uint256 word)
        uint256[] memory idsBig = new uint256[](1);
        idsBig[0] = type(uint256).max;
        console.log("--- vector3: tier=Common ids=[uint256max] ws=1 exp=2 nonce=1");
        console.logBytes32(m.claimDigest(WALLET, "Common", idsBig, 1, 2, 1));
    }
}
