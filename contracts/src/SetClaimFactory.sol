// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {SetClaimManager} from "./SetClaimManager.sol";

/// @title SetClaimFactory
/// @notice Deploys one `SetClaimManager` per project/season and keeps an on-chain
///         registry of every season so the frontend/backend can discover the
///         canonical season contract for a collection.
/// @dev    `deploySeason` is gated to the platform `owner` (the "platform operator"
///         resolution of the ManifestRegistry access-control question): the platform
///         already runs the trusted backend signer, so it is the party that spins up
///         a season once a project's atlas is approved + locked. Permissioning the
///         deploy keeps the registry free of spoofed seasons pointing at a collection.
///         Each deployed season is owned by this factory's `owner` (not the factory),
///         so the platform retains signer-rotation on every season.
contract SetClaimFactory {
    struct Season {
        address manager;
        address nftContract;
        bytes32 atlasHash;
        uint256 deployedAt;
    }

    /// @notice Platform admin: may deploy seasons and rotate ownership.
    address public owner;

    /// @notice All seasons ever deployed, in order.
    Season[] public seasons;

    /// @dev nftContract => indices into `seasons` (a collection may run many seasons).
    mapping(address nftContract => uint256[] seasonIndexes) internal _seasonsByContract;

    event SeasonDeployed(
        address indexed manager,
        address indexed nftContract,
        bytes32 atlasHash,
        address backendSigner,
        uint256 seasonIndex
    );
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    constructor() {
        owner = msg.sender;
        emit OwnershipTransferred(address(0), msg.sender);
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    /// @notice Transfer platform admin rights (which `ManifestRegistry` lacks).
    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "owner=0");
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    /// @notice Deploy a new season for `nftContract` and record it.
    /// @param nftContract  Collection the season races over.
    /// @param atlasHash    Locked atlas-manifest hash (as committed in ManifestRegistry).
    /// @param backendSigner Trusted signer whose attestation authorizes that season's claims.
    /// @param tierNames    Tier labels; unique, non-empty.
    /// @param caps         Per-tier slot cap (> 0), positionally aligned with tierNames.
    /// @param windows      Per-tier holding window in seconds, positionally aligned.
    /// @return manager     The deployed `SetClaimManager` address.
    function deploySeason(
        address nftContract,
        bytes32 atlasHash,
        address backendSigner,
        string[] calldata tierNames,
        uint256[] calldata caps,
        uint256[] calldata windows
    ) external onlyOwner returns (address manager) {
        // The season is owned by the platform admin (this factory's owner), not by
        // the factory contract — so `setBackendSigner` remains callable by the admin.
        SetClaimManager season =
            new SetClaimManager(owner, nftContract, atlasHash, backendSigner, tierNames, caps, windows);
        manager = address(season);

        uint256 seasonIndex = seasons.length;
        seasons.push(
            Season({
                manager: manager,
                nftContract: nftContract,
                atlasHash: atlasHash,
                deployedAt: block.timestamp
            })
        );
        _seasonsByContract[nftContract].push(seasonIndex);

        emit SeasonDeployed(manager, nftContract, atlasHash, backendSigner, seasonIndex);
    }

    // --- Views ---

    /// @notice Total number of seasons deployed across all collections.
    function seasonCount() external view returns (uint256) {
        return seasons.length;
    }

    /// @notice Number of seasons deployed for a specific collection.
    function seasonCountFor(address nftContract) external view returns (uint256) {
        return _seasonsByContract[nftContract].length;
    }

    /// @notice All season manager addresses for a collection (oldest → newest).
    function seasonsFor(address nftContract) external view returns (address[] memory managers) {
        uint256[] storage idxs = _seasonsByContract[nftContract];
        managers = new address[](idxs.length);
        for (uint256 i = 0; i < idxs.length; i++) {
            managers[i] = seasons[idxs[i]].manager;
        }
    }

    /// @notice The most recently deployed season for a collection.
    /// @dev Reverts if the collection has no seasons.
    function latestSeason(address nftContract) external view returns (address) {
        uint256[] storage idxs = _seasonsByContract[nftContract];
        require(idxs.length > 0, "No seasons");
        return seasons[idxs[idxs.length - 1]].manager;
    }
}
