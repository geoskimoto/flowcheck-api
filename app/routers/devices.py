from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user_id
from app.models.device import Device
from app.schemas.alert import DeviceRegisterRequest

router = APIRouter(prefix="/devices", tags=["devices"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register_device(body: DeviceRegisterRequest, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    existing = db.query(Device).filter(Device.fcm_token == body.fcm_token).first()
    if existing:
        existing.user_id = user_id
        existing.platform = body.platform
    else:
        db.add(Device(user_id=user_id, fcm_token=body.fcm_token, platform=body.platform))
    db.commit()
    return {"status": "registered"}
