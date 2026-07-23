// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title SetClaimManager
/// @notice One instance per project per season. Awards a bounded number of slots
///         ("first N per tier") to wallets that prove — via a backend attestation —
///         that they held a qualifying set long enough. Eligibility, holding-window
///         tracking, and rarity are all computed off-chain; this contract is the
///         trustless bridge that enforces the cap, prevents replay, and records the
///         winner immutably.
/// @dev    Mirrors ManifestRegistry's self-contained ECDSA (no OpenZeppelin): EIP-2
///         low-`s` malleability guard, and a digest bound to `block.chainid` +
///         `address(this)` so an attestation can't be replayed on another chain or
///         a different season. There is deliberately NO per-wallet cap — a whale
///         may sweep multiple slots in a tier with reusable tokens (product
///         decision). Dedup is by single-use `nonce` (one signature = one slot) and
///         the cap. Caps + holding windows are frozen at construction (per season).
contract SetClaimManager {
    struct Tier {
        uint256 cap; // max slots awardable in this tier
        uint256 windowSeconds; // required continuous holding duration
        uint256 claimed; // slots awarded so far (also the next slot number - 1)
        bool exists;
    }

    /// @notice The NFT collection this season races over (informational + digest binding).
    address public immutable nftContract;

    /// @notice The locked atlas-manifest hash this season was deployed against.
    bytes32 public immutable atlasHash;

    /// @notice Platform admin; may rotate the backend signer.
    address public owner;

    /// @notice Trusted backend key whose attestation authorizes a claim.
    address public backendSigner;

    /// @dev tierId (keccak256 of the tier name) => config. Frozen after construction.
    mapping(bytes32 tierId => Tier tier) public tiers;

    /// @dev Enumeration of configured tiers (for off-chain discovery / views).
    bytes32[] public tierIds;

    /// @notice Single-use claim nonces (replay protection). Backend issues each once.
    mapping(uint256 nonce => bool used) public nonceUsed;

    event SeasonInitialized(address indexed nftContract, bytes32 atlasHash, address backendSigner);
    event TierConfigured(bytes32 indexed tierId, string tier, uint256 cap, uint256 windowSeconds);
    event BackendSignerUpdated(address indexed previousSigner, address indexed newSigner);
    event Claimed(
        bytes32 indexed tierId,
        string tier,
        address indexed wallet,
        uint256 slotNumber,
        uint256[] tokenIds,
        uint256 nonce,
        uint256 windowStartedAt
    );

    /// @param _owner        Admin who may rotate the backend signer (the platform,
    ///                      NOT the deploying factory — passed explicitly so a
    ///                      factory-deployed season isn't owned by the factory).
    /// @param _nftContract  Collection this season races over.
    /// @param _atlasHash    Locked atlas-manifest hash (as committed in ManifestRegistry).
    /// @param _backendSigner Trusted signer whose attestation authorizes claims.
    /// @param tierNames     Tier labels (e.g. "Common"); must be unique and non-empty.
    /// @param caps          Per-tier slot cap (> 0), positionally aligned with tierNames.
    /// @param windows       Per-tier required holding window in seconds, positionally aligned.
    constructor(
        address _owner,
        address _nftContract,
        bytes32 _atlasHash,
        address _backendSigner,
        string[] memory tierNames,
        uint256[] memory caps,
        uint256[] memory windows
    ) {
        require(_owner != address(0), "owner=0");
        require(_nftContract != address(0), "nftContract=0");
        require(_backendSigner != address(0), "backendSigner=0");
        require(tierNames.length > 0, "no tiers");
        require(tierNames.length == caps.length && caps.length == windows.length, "tier arity mismatch");

        nftContract = _nftContract;
        atlasHash = _atlasHash;
        owner = _owner;
        backendSigner = _backendSigner;

        for (uint256 i = 0; i < tierNames.length; i++) {
            require(bytes(tierNames[i]).length > 0, "empty tier name");
            require(caps[i] > 0, "cap=0");
            bytes32 tierId = keccak256(bytes(tierNames[i]));
            require(!tiers[tierId].exists, "duplicate tier");
            tiers[tierId] = Tier({cap: caps[i], windowSeconds: windows[i], claimed: 0, exists: true});
            tierIds.push(tierId);
            emit TierConfigured(tierId, tierNames[i], caps[i], windows[i]);
        }

        emit SeasonInitialized(_nftContract, _atlasHash, _backendSigner);
    }

    /// @notice Rotate the trusted backend signer (e.g. key rotation/compromise).
    function setBackendSigner(address newSigner) external {
        require(msg.sender == owner, "Not owner");
        require(newSigner != address(0), "backendSigner=0");
        emit BackendSignerUpdated(backendSigner, newSigner);
        backendSigner = newSigner;
    }

    /// @notice Claim a slot in `tier`. The caller (`msg.sender`) is the beneficiary;
    ///         the backend attestation must be issued for exactly this wallet, tier,
    ///         token set, window, expiry, and nonce.
    /// @dev Check order (per PROJECT_MASTER §6): tier exists → not expired →
    ///      nonce unused → cap not full → holding window elapsed → signature valid →
    ///      award. There is intentionally no "already claimed by this wallet" check.
    /// @param tier            Tier label (must match a configured tier).
    /// @param tokenIds        The qualifying token ids (recorded in the event; bound in the signature).
    /// @param windowStartedAt Unix seconds the holding window started (attested off-chain).
    /// @param expiry          Unix seconds after which the signature is void (backend sets ~1h out).
    /// @param nonce           Single-use nonce issued by the backend.
    /// @param signature       EIP-191 personal_sign by `backendSigner` over `claimDigest(...)`.
    function claim(
        string calldata tier,
        uint256[] calldata tokenIds,
        uint256 windowStartedAt,
        uint256 expiry,
        uint256 nonce,
        bytes calldata signature
    ) external {
        bytes32 tierId = keccak256(bytes(tier));
        Tier storage t = tiers[tierId];

        require(t.exists, "Unknown tier");
        require(block.timestamp <= expiry, "Signature expired");
        require(!nonceUsed[nonce], "Nonce used");
        require(t.claimed < t.cap, "Tier full");
        require(tokenIds.length > 0, "No tokens");
        require(windowStartedAt > 0, "No window start");
        require(block.timestamp >= windowStartedAt + t.windowSeconds, "Window not elapsed");

        bytes32 ethHash = _toEthSignedMessageHash(
            claimDigest(msg.sender, tier, tokenIds, windowStartedAt, expiry, nonce)
        );
        require(_recover(ethHash, signature) == backendSigner, "Unauthorized: bad backend signature");

        nonceUsed[nonce] = true;
        uint256 slotNumber = ++t.claimed; // 1-indexed
        emit Claimed(tierId, tier, msg.sender, slotNumber, tokenIds, nonce, windowStartedAt);
    }

    /// @notice The inner message the backend signs (before the EIP-191 prefix).
    ///         Bound to chainId + this season contract so an attestation can't be
    ///         replayed on another chain or a different season. `tokenIds` is hashed
    ///         separately to keep the packed encoding unambiguous.
    function claimDigest(
        address wallet,
        string calldata tier,
        uint256[] calldata tokenIds,
        uint256 windowStartedAt,
        uint256 expiry,
        uint256 nonce
    ) public view returns (bytes32) {
        return keccak256(
            abi.encodePacked(
                block.chainid,
                address(this),
                nftContract,
                wallet,
                keccak256(bytes(tier)),
                keccak256(abi.encodePacked(tokenIds)),
                windowStartedAt,
                expiry,
                nonce
            )
        );
    }

    // --- Views ---

    /// @notice Number of configured tiers.
    function tierCount() external view returns (uint256) {
        return tierIds.length;
    }

    /// @notice Slots remaining in a tier (0 if unknown/full).
    function slotsRemaining(string calldata tier) external view returns (uint256) {
        Tier storage t = tiers[keccak256(bytes(tier))];
        if (!t.exists || t.claimed >= t.cap) return 0;
        return t.cap - t.claimed;
    }

    // --- ECDSA (self-contained; mirrors ManifestRegistry / OZ's MessageHashUtils + ECDSA) ---

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
