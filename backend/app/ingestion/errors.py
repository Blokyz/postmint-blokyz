"""Ingestion errors — non-retryable unless noted."""


class IngestError(Exception):
    """Base class for ingestion failures that should not be retried."""


class EmptyCollectionError(IngestError):
    """Moralis returned no NFTs for the contract/chain."""


class MoralisApiError(IngestError):
    """Moralis HTTP OK but no usable NFT data (plan, indexing, or quota)."""
