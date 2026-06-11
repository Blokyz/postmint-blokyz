import re

from pydantic import BaseModel, field_validator

_ETH_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


class IngestRequest(BaseModel):
    contract_address: str
    chain: str = "eth"

    @field_validator("contract_address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        v = v.strip().lower()
        if not _ETH_ADDRESS_RE.match(v):
            raise ValueError("contract_address must be a valid EVM address (0x + 40 hex chars)")
        return v


class IngestResponse(BaseModel):
    job_id: str
    contract_address: str
    status: str
    message: str


class StatusResponse(BaseModel):
    contract_address: str
    job_id: str | None
    status: str | None
    progress_pct: int | None
    error_message: str | None


class TraitApproval(BaseModel):
    trait_category: str
    trait_value: str
    pinned: bool = False


class ApproveRequest(BaseModel):
    contract_address: str
    approver_address: str
    trait_rankings: list[TraitApproval]

    @field_validator("contract_address", "approver_address")
    @classmethod
    def validate_addresses(cls, v: str) -> str:
        v = v.strip().lower()
        if not _ETH_ADDRESS_RE.match(v):
            raise ValueError("must be a valid EVM address (0x + 40 hex chars)")
        return v


class ApproveResponse(BaseModel):
    contract_address: str
    manifest_hash: str
    approved_at: str
    approver_address: str
    trait_count: int
