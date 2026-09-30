from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.dependencies import get_current_user, require_centre_owner
from app.models import DiagnosticCentre, DiagnosticTest, User
from app.schemas import CentreCreate, CentreRead, CentreUpdate, TestCreate, TestRead, TestUpdate


router = APIRouter(tags=["Diagnostic centres and tests"])


@router.get("/centres", response_model=list[CentreRead])
def list_centres(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[DiagnosticCentre]:
    statement = (
        select(DiagnosticCentre)
        .where(DiagnosticCentre.is_active.is_(True))
        .options(selectinload(DiagnosticCentre.tests.and_(DiagnosticTest.is_active.is_(True))))
        .order_by(DiagnosticCentre.name)
        .offset(offset)
        .limit(limit)
    )
    return list(db.scalars(statement).all())


@router.post("/centres", response_model=CentreRead, status_code=status.HTTP_201_CREATED)
def create_centre(
    payload: CentreCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DiagnosticCentre:
    centre = DiagnosticCentre(name=payload.name.strip(), location=payload.location.strip(), owner_id=user.id)
    db.add(centre)
    db.commit()
    db.refresh(centre)
    return centre


@router.get("/centres/{centre_id}", response_model=CentreRead)
def get_centre(centre_id: int, db: Session = Depends(get_db)) -> DiagnosticCentre:
    statement = (
        select(DiagnosticCentre)
        .where(DiagnosticCentre.id == centre_id, DiagnosticCentre.is_active.is_(True))
        .options(selectinload(DiagnosticCentre.tests.and_(DiagnosticTest.is_active.is_(True))))
    )
    centre = db.scalar(statement)
    if centre is None:
        raise HTTPException(status_code=404, detail="Diagnostic centre not found")
    return centre


@router.patch("/centres/{centre_id}", response_model=CentreRead)
def update_centre(
    centre_id: int,
    payload: CentreUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DiagnosticCentre:
    centre = db.get(DiagnosticCentre, centre_id)
    if centre is None or not centre.is_active:
        raise HTTPException(status_code=404, detail="Diagnostic centre not found")
    require_centre_owner(centre.owner_id, user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(centre, field, value.strip())
    db.commit()
    db.refresh(centre)
    return centre


@router.delete("/centres/{centre_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_centre(
    centre_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    centre = db.get(DiagnosticCentre, centre_id)
    if centre is None or not centre.is_active:
        raise HTTPException(status_code=404, detail="Diagnostic centre not found")
    require_centre_owner(centre.owner_id, user)
    centre.is_active = False
    for diagnostic_test in centre.tests:
        diagnostic_test.is_active = False
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/centres/{centre_id}/tests", response_model=list[TestRead])
def list_tests(centre_id: int, db: Session = Depends(get_db)) -> list[DiagnosticTest]:
    centre = db.get(DiagnosticCentre, centre_id)
    if centre is None or not centre.is_active:
        raise HTTPException(status_code=404, detail="Diagnostic centre not found")
    statement = select(DiagnosticTest).where(
        DiagnosticTest.centre_id == centre_id, DiagnosticTest.is_active.is_(True)
    ).order_by(DiagnosticTest.name)
    return list(db.scalars(statement).all())


@router.post(
    "/centres/{centre_id}/tests", response_model=TestRead, status_code=status.HTTP_201_CREATED
)
def create_test(
    centre_id: int,
    payload: TestCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DiagnosticTest:
    centre = db.get(DiagnosticCentre, centre_id)
    if centre is None or not centre.is_active:
        raise HTTPException(status_code=404, detail="Diagnostic centre not found")
    require_centre_owner(centre.owner_id, user)
    diagnostic_test = DiagnosticTest(centre_id=centre_id, **payload.model_dump())
    db.add(diagnostic_test)
    db.commit()
    db.refresh(diagnostic_test)
    return diagnostic_test


@router.patch("/tests/{test_id}", response_model=TestRead)
def update_test(
    test_id: int,
    payload: TestUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DiagnosticTest:
    diagnostic_test = db.get(DiagnosticTest, test_id)
    if diagnostic_test is None or not diagnostic_test.is_active:
        raise HTTPException(status_code=404, detail="Diagnostic test not found")
    centre = db.get(DiagnosticCentre, diagnostic_test.centre_id)
    require_centre_owner(centre.owner_id, user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None or field == "description":
            setattr(diagnostic_test, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    db.refresh(diagnostic_test)
    return diagnostic_test


@router.delete("/tests/{test_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_test(
    test_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    diagnostic_test = db.get(DiagnosticTest, test_id)
    if diagnostic_test is None or not diagnostic_test.is_active:
        raise HTTPException(status_code=404, detail="Diagnostic test not found")
    centre = db.get(DiagnosticCentre, diagnostic_test.centre_id)
    require_centre_owner(centre.owner_id, user)
    diagnostic_test.is_active = False
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)