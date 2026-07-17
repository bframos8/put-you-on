from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..db.database import get_db
from ..db.models import User
from ..core.session import decode_session
def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = decode_session(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Session expired")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

