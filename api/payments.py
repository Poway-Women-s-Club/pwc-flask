from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from model.database import db
from model.payment import Payment

payments_bp = Blueprint("payments", __name__)

MEMBERSHIP_DUES_CENTS = 5000  # $50.00 — adjust as needed


@payments_bp.route("/dues", methods=["POST"])
@login_required
def pay_dues():
    """
    Stub for membership payment.
    In production, this would create a Stripe checkout session
    and return a redirect URL. For now it just records the payment.
    """
    payment = Payment(
        user_id=current_user.id,
        amount_cents=MEMBERSHIP_DUES_CENTS,
        description="Annual Membership Dues",
        status="completed",  # would be "pending" with real payment flow
        payment_method="stub",
    )
    db.session.add(payment)

    # Mark user as active member
    current_user.is_active_member = True
    db.session.commit()

    return jsonify({
        "message": "Payment recorded",
        "payment": payment.to_dict(),
    }), 201


@payments_bp.route("/history", methods=["GET"])
@login_required
def payment_history():
    payments = Payment.query.filter_by(user_id=current_user.id).order_by(
        Payment.created_at.desc()
    ).all()
    return jsonify([p.to_dict() for p in payments])