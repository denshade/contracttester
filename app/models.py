from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, TypeDecorator, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    access_token: Mapped[str | None] = mapped_column(String(128), unique=True)

    users: Mapped[list["User"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    contracts: Mapped[list["Contract"]] = relationship(back_populates="company", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200))
    username: Mapped[str | None] = mapped_column(String(200), unique=True)
    password: Mapped[str | None] = mapped_column(String(200))

    company: Mapped[Company] = relationship(back_populates="users")


class Contract(Base):
    __tablename__ = "contracts"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_contract_name_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column()

    company: Mapped[Company] = relationship(back_populates="contracts")
    publisher: Mapped[Optional["Publisher"]] = relationship(
        back_populates="contract",
        cascade="all, delete-orphan",
        uselist=False,
    )
    statements: Mapped[list["Statement"]] = relationship(
        back_populates="contract",
        cascade="all, delete-orphan",
        order_by="Statement.id",
    )

    @property
    def publisher_name(self) -> str:
        if self.publisher is None:
            return ""
        return self.publisher.name


class Publisher(Base):
    __tablename__ = "publishers"

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"), unique=True)
    name: Mapped[str] = mapped_column(String(200))

    contract: Mapped[Contract] = relationship(back_populates="publisher")


class Statement(Base):
    __tablename__ = "statements"

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"), index=True)
    trigger: Mapped[str] = mapped_column(String(500))
    expected_state: Mapped[str] = mapped_column(String(2000))
    payload: Mapped[str] = mapped_column(Text, default="")

    contract: Mapped[Contract] = relationship(back_populates="statements")
    verifiers: Mapped[list["Verifier"]] = relationship(
        back_populates="statement",
        cascade="all, delete-orphan",
        order_by="Verifier.id",
    )

    @property
    def contract_version(self) -> int:
        return self.contract.version


class Verifier(Base):
    __tablename__ = "verifiers"

    id: Mapped[int] = mapped_column(primary_key=True)
    statement_id: Mapped[int] = mapped_column(ForeignKey("statements.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column()
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    verification_trigger: Mapped[str] = mapped_column(String(500), default="")
    last_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    statement: Mapped[Statement] = relationship(back_populates="verifiers")
    tests: Mapped[list["VerifierTest"]] = relationship(
        back_populates="verifier",
        cascade="all, delete-orphan",
        order_by="VerifierTest.id",
    )


class VerifierTest(Base):
    __tablename__ = "tests"

    id: Mapped[int] = mapped_column(primary_key=True)
    verifier_id: Mapped[int] = mapped_column(ForeignKey("verifiers.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))

    verifier: Mapped[Verifier] = relationship(back_populates="tests")
