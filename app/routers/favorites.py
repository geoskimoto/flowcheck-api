from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.dependencies import get_db, get_current_user_id
from app.models.favorite_station import FavoriteStation
from app.schemas.favorite import FavoriteRequest, FavoriteResponse

router = APIRouter(prefix="/favorites", tags=["favorites"])


@router.get("/", response_model=list[FavoriteResponse])
def list_favorites(user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    return db.query(FavoriteStation).filter(FavoriteStation.user_id == user_id).all()


@router.post("/", response_model=FavoriteResponse, status_code=status.HTTP_201_CREATED)
def add_favorite(body: FavoriteRequest, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    fav = FavoriteStation(user_id=user_id, station_number=body.station_number)
    db.add(fav)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Station already in favorites")
    db.refresh(fav)
    return fav


@router.delete("/{station_number}", status_code=status.HTTP_204_NO_CONTENT)
def remove_favorite(station_number: str, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    fav = db.query(FavoriteStation).filter(
        FavoriteStation.user_id == user_id,
        FavoriteStation.station_number == station_number,
    ).first()
    if not fav:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Favorite not found")
    db.delete(fav)
    db.commit()
