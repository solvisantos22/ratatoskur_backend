from uuid import UUID

from sqlmodel import Session, select

from backend.models.auth_models import Problem
from backend.models.classroom_models import (
    Assignment,
    AssignmentItem,
    ClassMembership,
    StudentAssignmentItem,
)


def assignment_item_for_problem(
    session: Session, *, problem_id: UUID, user_id: UUID
) -> AssignmentItem | None:
    """Resolve only a current member's own assignment notebook association."""
    return session.exec(
        select(AssignmentItem)
        .join(StudentAssignmentItem, StudentAssignmentItem.item_id == AssignmentItem.id)
        .join(
            Problem,
            (Problem.id == StudentAssignmentItem.problem_id)
            & (Problem.user_id == StudentAssignmentItem.user_id),
        )
        .join(Assignment, Assignment.id == AssignmentItem.assignment_id)
        .join(
            ClassMembership,
            (ClassMembership.class_id == Assignment.class_id)
            & (ClassMembership.user_id == StudentAssignmentItem.user_id),
        )
        .where(Problem.id == problem_id, Problem.user_id == user_id)
    ).first()
