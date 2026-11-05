from fastapi import APIRouter

from app.services.excel_parser import parse_excel_and_save

router = APIRouter(prefix="/import", tags=["import"])


@router.post("/")
def manual_import():
    return parse_excel_and_save()
