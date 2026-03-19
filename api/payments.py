"""
Payments API — membership dues and history.

SRP: Payment creation, user activation, and history query are separate.
Orchestrator: Routes chain helpers.
Error handling: @handle_errors on every route.
"""

from flask import Blueprint, jsonify

from model.database import db
from model.payment import Payment
from api.utils import handle_errors, require_auth

payments_bp = Blueprint("payments", __name__)

MEMBERSHIP_DUES_CENTS = 5000  # $50.00


# ── Single-responsibility helpers ──

def record_payment(user_id, amount_cents, description):
    """Create a payment record in the database."""
    payment = Payment(
        user_id=user_id,
        amount_cents=amount_cents,
        description=description,
        status="completed",
        payment_method="stub",
    )
    db.session.add(payment)
    return payment


def activate_membership(user):
    """Mark a user as an active member."""
    user.is_active_member = True


def get_user_payments(user_id):
    """Fetch all payments for a user, newest first."""
    return Payment.query.filter_by(user_id=user_id).order_by(
        Payment.created_at.desc()
    ).all()


# ── Orchestrator routes ──

@payments_bp.route("/dues", methods=["POST"])
@handle_errors
def pay_dues():
    """Orchestrator: require auth → record payment → activate membership → respond."""
    user = require_auth()
    payment = record_payment(user.id, MEMBERSHIP_DUES_CENTS, "Annual Membership Dues")
    activate_membership(user)
    db.session.commit()
    return jsonify({"message": "Payment recorded", "payment": payment.to_dict()}), 201


@payments_bp.route("/history", methods=["GET"])
@handle_errors
def payment_history():
    """Orchestrator: require auth → query payments → respond."""
    user = require_auth()
    payments = get_user_payments(user.id)
    return jsonify([p.to_dict() for p in payments])