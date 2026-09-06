"""Teacher-owned classes; every assignment item gets a private student notebook."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Column, DateTime, String, UniqueConstraint, true
from sqlmodel import Field, SQLModel

from backend.models.auth_models import utcnow


class Classroom(SQLModel, table=True):
    __tablename__ = "classrooms"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    teacher_id: UUID = Field(foreign_key="users.id", index=True)
    name: str = Field(sa_column=Column(String(128), nullable=False))
    join_code: str = Field(sa_column=Column(String(12), nullable=False, unique=True))
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ClassMembership(SQLModel, table=True):
    __tablename__ = "class_memberships"
    class_id: UUID = Field(foreign_key="classrooms.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True, index=True)
    joined_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class Assignment(SQLModel, table=True):
    __tablename__ = "assignments"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    class_id: UUID = Field(foreign_key="classrooms.id", index=True)
    title: str = Field(sa_column=Column(String(255), nullable=False))
    allow_reveal: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, server_default=true()))
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class AssignmentItem(SQLModel, table=True):
    __tablename__ = "assignment_items"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    assignment_id: UUID = Field(foreign_key="assignments.id", index=True)
    title: str = Field(sa_column=Column(String(255), nullable=False))
    position: int
    image_key: str = Field(sa_column=Column(String(1024), nullable=False))
    __table_args__ = (
        UniqueConstraint(
            "assignment_id", "position", name="uq_assignment_item_position"
        ),
    )


class StudentAssignmentItem(SQLModel, table=True):
    __tablename__ = "student_assignment_items"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    item_id: UUID = Field(foreign_key="assignment_items.id", index=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    problem_id: UUID | None = Field(
        default=None, foreign_key="problems.id", ondelete="SET NULL", unique=True
    )
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    __table_args__ = (
        UniqueConstraint("item_id", "user_id", name="uq_student_assignment_item"),
    )
