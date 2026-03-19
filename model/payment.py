"""Payment model."""

from datetime import datetime
from model.database import db


class Payment(db.Model):
    __tablename__ = "payments"

    id             = db.Column(db.Integer,     primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    amount_cents   = db.Column(db.Integer,     nullable=False)
    description    = db.Column(db.String(255), nullable=False, default="")
    status         = db.Column(db.String(50),  nullable=False, default="pending")
    payment_method = db.Column(db.String(50),  nullable=False, default="stub")
    created_at     = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id":             self.id,
            "user_id":        self.user_id,
            "amount_cents":   self.amount_cents,
            "amount":         self.amount_cents / 100,
            "description":    self.description,
            "status":         self.status,
            "payment_method": self.payment_method,
            "created_at":     self.created_at.isoformat(),
        }