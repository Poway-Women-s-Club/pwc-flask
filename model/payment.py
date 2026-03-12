from datetime import datetime
from model.database import db


class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False)  # store in cents
    description = db.Column(db.String(200), default="Membership Dues")
    status = db.Column(db.String(20), default="pending")  # pending, completed, failed
    payment_method = db.Column(db.String(50), nullable=True)  # placeholder for Stripe etc.
    transaction_id = db.Column(db.String(256), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref="payments")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "amount": self.amount_cents / 100,
            "description": self.description,
            "status": self.status,
            "payment_method": self.payment_method,
            "created_at": self.created_at.isoformat(),
        }