// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title ManifestRegistry
/// @notice Locks approved ranking + atlas manifest hashes per NFT collection (immutable after lock).
contract ManifestRegistry {
    struct Manifest {
        bytes32 rankingManifestHash;
        bytes32 atlasManifestHash;
        address approver;
        uint256 approvedAt;
        bool locked;
    }

    mapping(address nftContract => Manifest manifest) public manifests;

    event ManifestLocked(
        address indexed nftContract,
        bytes32 rankingManifestHash,
        bytes32 atlasManifestHash,
        address indexed approver
    );

    /// @notice Project approver (connected wallet) commits to ranking + atlas manifests.
    function lockManifest(
        address nftContract,
        bytes32 rankingHash,
        bytes32 atlasHash
    ) external {
        require(nftContract != address(0), "Invalid contract");
        require(!manifests[nftContract].locked, "Already locked");
        manifests[nftContract] = Manifest({
            rankingManifestHash: rankingHash,
            atlasManifestHash: atlasHash,
            approver: msg.sender,
            approvedAt: block.timestamp,
            locked: true
        });
        emit ManifestLocked(nftContract, rankingHash, atlasHash, msg.sender);
    }

    function verifyAtlas(address nftContract, bytes32 atlasHash) external view returns (bool) {
        return manifests[nftContract].atlasManifestHash == atlasHash;
    }

    function isLocked(address nftContract) external view returns (bool) {
        return manifests[nftContract].locked;
    }
}
