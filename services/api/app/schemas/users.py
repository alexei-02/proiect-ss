"""Admin user management schemas."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

VALID_ROLES = frozenset({"admin", "doctor", "receptionist", "auditor"})


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$")
    password: str = Field(..., min_length=12, max_length=256)
    roles: list[str] = Field(..., min_length=1)

    @field_validator("roles")
    @classmethod
    def validate_roles(cls, v: list[str]) -> list[str]:
        invalid = set(v) - VALID_ROLES
        if invalid:
            raise ValueError(f"Invalid roles: {sorted(invalid)}. Valid roles: {sorted(VALID_ROLES)}")
        return list(dict.fromkeys(v))  # deduplicate, preserve order


class UpdateUserRequest(BaseModel):
    roles: list[str] | None = None
    is_active: bool | None = None
    password: str | None = Field(None, min_length=12, max_length=256)

    @model_validator(mode="after")
    def at_least_one_field(self) -> "UpdateUserRequest":
        if self.roles is None and self.is_active is None and self.password is None:
            raise ValueError("At least one of roles, is_active, or password must be provided")
        return self

    @field_validator("roles")
    @classmethod
    def validate_roles(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        if not v:
            raise ValueError("roles must not be empty")
        invalid = set(v) - VALID_ROLES
        if invalid:
            raise ValueError(f"Invalid roles: {sorted(invalid)}. Valid roles: {sorted(VALID_ROLES)}")
        return list(dict.fromkeys(v))


class UserResponse(BaseModel):
    id: str
    username: str
    roles: list[str]
    is_active: bool
    created_at: datetime | None
    last_login_at: datetime | None


class UserListResponse(BaseModel):
    users: list[UserResponse]
    total: int
