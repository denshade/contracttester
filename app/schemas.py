import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def required_text(value: str, label: str, max_length: int = 200) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{label} is required")
    if len(cleaned) > max_length:
        raise ValueError(f"{label} must be at most {max_length} characters")
    return cleaned


def required_email(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) > 200 or not EMAIL_PATTERN.fullmatch(cleaned):
        raise ValueError("Email must be a valid email address")
    return cleaned


class CompanyCreate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return required_text(value, "Organization name")


class CompanyUpdate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return required_text(value, "Organization name")


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class UserWrite(BaseModel):
    name: str
    email: str

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return required_text(value, "Name")

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str) -> str:
        return required_email(value)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    company_id: int


class StatementWrite(BaseModel):
    trigger: str
    expected_state: str
    payload: str = ""

    @field_validator("trigger")
    @classmethod
    def clean_trigger(cls, value: str) -> str:
        return required_text(value, "Trigger endpoint", 500)

    @field_validator("expected_state")
    @classmethod
    def clean_expected_state(cls, value: str) -> str:
        return required_text(value, "Expected state", 2000)

    @field_validator("payload")
    @classmethod
    def clean_payload(cls, value: str) -> str:
        if len(value) > 20000:
            raise ValueError("Payload must be at most 20000 characters")
        return value


class StatementCreate(StatementWrite):
    contract_id: int


class ContractCreate(BaseModel):
    name: str
    publisher_name: str
    statements: list[StatementWrite] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return required_text(value, "Name")

    @field_validator("publisher_name")
    @classmethod
    def clean_publisher_name(cls, value: str) -> str:
        return required_text(value, "Publisher name")


class ContractUpdate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return required_text(value, "Name")


class ContractOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    version: int
    company_id: int
    publisher_name: str


class StatementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contract_id: int
    contract_version: int
    trigger: str
    expected_state: str
    payload: str


class StatementRemoval(BaseModel):
    statement_id: int
    contract: ContractOut


class VerifierWrite(BaseModel):
    statement_id: int
    name: str
    version: int
    active: bool = True
    verification_trigger: str
    last_verified_at: datetime | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return required_text(value, "Verifier name")

    @field_validator("verification_trigger")
    @classmethod
    def clean_trigger(cls, value: str) -> str:
        return required_text(value, "Verification trigger", 500)


class VerifierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    statement_id: int
    name: str
    version: int
    active: bool
    verification_trigger: str
    last_verified_at: datetime | None


class TestWrite(BaseModel):
    verifier_id: int
    name: str

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return required_text(value, "Test name")


class TestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    verifier_id: int
    name: str


class PublisherWrite(BaseModel):
    contract_id: int
    name: str

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return required_text(value, "Publisher name")


class PublisherOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contract_id: int
    name: str
