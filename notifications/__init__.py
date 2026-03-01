# notifications/__init__.py
import logging
from flask import Blueprint, jsonify
from sqlalchemy import MetaData, Table, select
from sqlalchemy.exc import SQLAlchemyError
from db import get_engine

notifications_bp = Blueprint("notifications", __name__)
log = logging.getLogger("app")


def _reflect_table():
    if not hasattr(notifications_bp, "_tbl"):
        engine = get_engine()
        md = MetaData()
        tbl = Table("notifications", md, autoload_with=engine)
        setattr(notifications_bp, "_tbl", tbl)
    return getattr(notifications_bp, "_tbl")


def _row_to_dict(row):
    return dict(row._mapping)


# ---------------------------------------------------------------------------
# PUT /api/v1/notifications/<id>/read
# ---------------------------------------------------------------------------
@notifications_bp.put("/notifications/<int:notif_id>/read")
def mark_read(notif_id: int):
    engine = get_engine()
    tbl = _reflect_table()

    try:
        with engine.connect() as conn:
            result = conn.execute(
                tbl.update().where(tbl.c.id == notif_id).values(is_read=1)
            )
            if result.rowcount == 0:
                return jsonify(error="not_found", message="Notification not found"), 404
            conn.commit()

            updated = conn.execute(
                select(tbl).where(tbl.c.id == notif_id)
            ).first()

        return jsonify(_row_to_dict(updated)), 200

    except SQLAlchemyError:
        log.exception("notifications mark_read: db error")
        return jsonify(error="db_unavailable", message="Database temporarily unavailable"), 503


# ---------------------------------------------------------------------------
# DELETE /api/v1/notifications/<id>
# ---------------------------------------------------------------------------
@notifications_bp.delete("/notifications/<int:notif_id>")
def delete_notification(notif_id: int):
    engine = get_engine()
    tbl = _reflect_table()

    try:
        with engine.connect() as conn:
            result = conn.execute(
                tbl.delete().where(tbl.c.id == notif_id)
            )
            if result.rowcount == 0:
                return jsonify(error="not_found", message="Notification not found"), 404
            conn.commit()

        return jsonify(ok=True), 200

    except SQLAlchemyError:
        log.exception("notifications delete: db error")
        return jsonify(error="db_unavailable", message="Database temporarily unavailable"), 503
