from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from backend.schemas.problem import ProblemCreateResponse


class ClassCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class JoinClassRequest(BaseModel):
    join_code: str = Field(min_length=1, max_length=32)


class ClassResponse(BaseModel):
    id: UUID
    name: str
    join_code: str
    student_count: int


class AssignmentSummary(BaseModel):
    id: UUID
    class_id: UUID
    class_name: str
    title: str
    item_count: int
    created_at: datetime


class AssignmentItemResponse(BaseModel):
    id: UUID
    title: str
    position: int
    image_url: str


class StudentAssignmentItemResponse(AssignmentItemResponse):
    problem_id: UUID | None = None


class StudentAssignmentResponse(AssignmentSummary):
    items: list[StudentAssignmentItemResponse]


class StudentProgress(BaseModel):
    id: UUID
    full_name: str | None
    completed_count: int
    attempt_count: int
    hint_count: int
    needs_attention: bool
    last_activity: datetime | None


class CommonError(BaseModel):
    error_type: str
    count: int


class AssignmentDetail(BaseModel):
    assignment: AssignmentSummary
    items: list[AssignmentItemResponse]
    students: list[StudentProgress]
    common_errors: list[CommonError]


class ClassroomAttemptResponse(BaseModel):
    id: UUID
    mode: str
    verdict: str | None
    response_type: str | None
    message_is: str | None
    created_at: datetime
    solution_image_url: str | None
    solution_page_urls: list[str]


class StudentWorkItem(StudentAssignmentItemResponse):
    attempts: list[ClassroomAttemptResponse]


class StudentIdentity(BaseModel):
    id: UUID
    full_name: str | None


class StudentWorkResponse(BaseModel):
    student: StudentIdentity
    assignment: AssignmentSummary
    items: list[StudentWorkItem]


class StartItemResponse(BaseModel):
    problem: ProblemCreateResponse
    image_url: str
