from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.dependencies import get_db, get_current_user_id
from app.models.alert_subscription import AlertSubscription
from app.models.alert_event import AlertEvent
from app.schemas.alert import AlertSubscriptionRequest, AlertSubscriptionResponse, AlertEventResponse

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("/subscriptions/", response_model=list[AlertSubscriptionResponse])
def list_subscriptions(user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    return db.query(AlertSubscription).filter(
        AlertSubscription.user_id == user_id,
        AlertSubscription.active == True,
    ).all()


@router.post("/subscriptions/", response_model=AlertSubscriptionResponse, status_code=status.HTTP_201_CREATED)
def subscribe(body: AlertSubscriptionRequest, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    sub = AlertSubscription(user_id=user_id, station_number=body.station_number)
    db.add(sub)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already subscribed to this station")
    db.refresh(sub)
    return sub


@router.delete("/subscriptions/{station_number}", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe(station_number: str, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    sub = db.query(AlertSubscription).filter(
        AlertSubscription.user_id == user_id,
        AlertSubscription.station_number == station_number,
        AlertSubscription.active == True,
    ).first()
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")
    db.delete(sub)
    db.commit()


@router.get("/history/", response_model=list[AlertEventResponse])
def alert_history(user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    subscribed_stations = [
        s.station_number for s in db.query(AlertSubscription).filter(
            AlertSubscription.user_id == user_id
        ).all()
    ]
    if not subscribed_stations:
        return []
    return db.query(AlertEvent).filter(
        AlertEvent.station_number.in_(subscribed_stations)
    ).order_by(AlertEvent.triggered_at.desc()).limit(50).all()
