// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title ManifestRegistry
/// @notice Locks approved ranking + atlas manifest hashes per NFT collection (immutable after lock).
/// @dev 
contract ManifestRegistry {
    struct Manifest {
        bytes32 rankingManifestHash;
        bytes32 atlasManifestHash;
        address approver;
        uint256 approvedAt;
        bool locked;
    }

    mapping(address nftContract => Manifest manifest) public manifests;

    /// @notice Platform admin; may rotate the backend signer.
    address public owner;

    /// @notice Trusted backend key whose attestation authorizes a lock.
    address public backendSigner;

    event ManifestLocked(
        address indexed nftContract,
        bytes32 rankingManifestHash,
        bytes32 atlasManifestHash,
        address indexed approver
    );

    event BackendSignerUpdated(address indexed previousSigner, address indexed newSigner);

    constructor(address _backendSigner) {
        require(_backendSigner != address(0), "backendSigner=0");
        owner = msg.sender;
        backendSigner = _backendSigner;
        emit BackendSignerUpdated(address(0), _backendSigner);
    }

    /// @notice Rotate the trusted backend signer (e.g. key rotation/compromise).
    function setBackendSigner(address newSigner) external {
        require(msg.sender == owner, "Not owner");
        require(newSigner != address(0), "backendSigner=0");
        emit BackendSignerUpdated(backendSigner, newSigner);
        backendSigner = newSigner;
    }

    /// @notice Project approver (connected wallet) commits to ranking + atlas
    ///         manifests, authorized by a backend attestation signature.
    /// @param backendSig EIP-191 personal_sign by `backendSigner` over `lockDigest(...)`.
    function lockManifest(
        address nftContract,
        bytes32 rankingHash,
        bytes32 atlasHash,
        bytes calldata backendSig
    ) external {
        require(nftContract != address(0), "Invalid contract");
        require(!manifests[nftContract].locked, "Already locked");

        bytes32 ethHash = _toEthSignedMessageHash(lockDigest(nftContract, rankingHash, atlasHash));
        require(_recover(ethHash, backendSig) == backendSigner, "Unauthorized: bad backend signature");

        manifests[nftContract] = Manifest({
            rankingManifestHash: rankingHash,
            atlasManifestHash: atlasHash,
            approver: msg.sender,
            approvedAt: block.timestamp,
            locked: true
        });
        emit ManifestLocked(nftContract, rankingHash, atlasHash, msg.sender);
    }

    /// @notice The inner message the backend signs (before the EIP-191 prefix).
    ///         Bound to chainId + this registry so an attestation can't be
    ///         replayed on another chain or a redeployed registry.
    
    function lockDigest(
        address nftContract,
        bytes32 rankingHash,
        bytes32 atlasHash
    ) public view returns (bytes32) {
        return keccak256(
            abi.encodePacked(block.chainid, address(this), nftContract, rankingHash, atlasHash)
        );
    }

    function verifyAtlas(address nftContract, bytes32 atlasHash) external view returns (bool) {
        return manifests[nftContract].atlasManifestHash == atlasHash;
    }

    function isLocked(address nftContract) external view returns (bool) {
        return manifests[nftContract].locked;
    }

    // --- ECDSA (self-contained; mirrors OZ's MessageHashUtils + ECDSA) ---

    function _toEthSignedMessageHash(bytes32 hash) private pure returns (bytes32) {
        return keccak256(abi.encodePacked("\x19Ethereum Signed Message:\n32", hash));
    }

    function _recover(bytes32 ethHash, bytes calldata sig) private pure returns (address) {
        require(sig.length == 65, "Bad sig length");
        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := calldataload(sig.offset)
            s := calldataload(add(sig.offset, 0x20))
            v := byte(0, calldataload(add(sig.offset, 0x40)))
        }
        if (v < 27) {
            v += 27;
        }
        require(v == 27 || v == 28, "Bad sig v");
        // Reject the upper-half (malleable) s per EIP-2.
        require(
            uint256(s) <= 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0,
            "Bad sig s"
        );
        address signer = ecrecover(ethHash, v, r, s);
        require(signer != address(0), "Bad signature");
        return signer;
    }
}
