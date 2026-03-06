"""Authentication & user management blueprint."""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db
from app.models import AuditLog, Role, User

auth_bp = Blueprint("auth", __name__, url_prefix="/auth", template_folder="../../templates/auth")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password) and user.is_active:
            login_user(user, remember=request.form.get("remember"))
            next_page = request.args.get("next")
            flash("Login successful.", "success")
            return redirect(next_page or url_for("dashboard"))
        flash("Invalid email or password.", "danger")
    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


# ── USER LIST ────────────────────────────────────────────────────────
@auth_bp.route("/users")
@login_required
def user_list():
    users = User.query.order_by(User.full_name).all()
    roles = Role.query.order_by(Role.name).all()
    return render_template("auth/user_list.html", users=users, roles=roles)


# ── CREATE USER ──────────────────────────────────────────────────────
@auth_bp.route("/users/create", methods=["POST"])
@login_required
def user_create():
    roles = Role.query.all()
    email = request.form.get("email", "").strip()
    full_name = request.form.get("full_name", "").strip()
    password = request.form.get("password", "")

    if not email or not full_name or not password:
        flash("All fields are required.", "danger")
        return redirect(url_for("auth.user_list"))

    if len(password) < 4:
        flash("Password must be at least 4 characters.", "danger")
        return redirect(url_for("auth.user_list"))

    if User.query.filter_by(email=email).first():
        flash(f"Email '{email}' already exists.", "danger")
        return redirect(url_for("auth.user_list"))

    user = User(email=email, full_name=full_name)
    user.set_password(password)

    for role_id in request.form.getlist("roles"):
        role = db.session.get(Role, int(role_id))
        if role:
            user.roles.append(role)

    db.session.add(user)
    db.session.flush()
    db.session.add(AuditLog(
        user_id=current_user.id,
        action="CREATE",
        table_name="users",
        record_id=user.id,
        new_values=f"email={email}, name={full_name}",
    ))
    db.session.commit()
    flash(f"User '{full_name}' created.", "success")
    return redirect(url_for("auth.user_list"))


# ── EDIT USER ────────────────────────────────────────────────────────
@auth_bp.route("/users/<int:user_id>/edit", methods=["POST"])
@login_required
def user_edit(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash("User not found.", "warning")
        return redirect(url_for("auth.user_list"))

    user.full_name = request.form.get("full_name", user.full_name).strip()
    new_email = request.form.get("email", user.email).strip()

    # Check email uniqueness
    if new_email != user.email:
        existing = User.query.filter_by(email=new_email).first()
        if existing:
            flash(f"Email '{new_email}' already in use.", "danger")
            return redirect(url_for("auth.user_list"))
        user.email = new_email

    # Update roles
    user.roles.clear()
    for role_id in request.form.getlist("roles"):
        role = db.session.get(Role, int(role_id))
        if role:
            user.roles.append(role)

    # Toggle active
    is_active = request.form.get("is_active")
    user.is_active = is_active == "on"

    db.session.commit()
    flash(f"User '{user.full_name}' updated.", "success")
    return redirect(url_for("auth.user_list"))


# ── CHANGE PASSWORD ──────────────────────────────────────────────────
@auth_bp.route("/users/<int:user_id>/password", methods=["POST"])
@login_required
def user_change_password(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash("User not found.", "warning")
        return redirect(url_for("auth.user_list"))

    new_password = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")

    if len(new_password) < 4:
        flash("Password must be at least 4 characters.", "danger")
        return redirect(url_for("auth.user_list"))

    if new_password != confirm:
        flash("Passwords don't match.", "danger")
        return redirect(url_for("auth.user_list"))

    user.set_password(new_password)
    db.session.commit()
    flash(f"Password changed for '{user.full_name}'.", "success")
    return redirect(url_for("auth.user_list"))


# ── DELETE USER ──────────────────────────────────────────────────────
@auth_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
def user_delete(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash("User not found.", "warning")
        return redirect(url_for("auth.user_list"))

    if user.id == current_user.id:
        flash("You cannot delete yourself.", "danger")
        return redirect(url_for("auth.user_list"))

    name = user.full_name
    db.session.add(AuditLog(
        user_id=current_user.id,
        action="DELETE",
        table_name="users",
        record_id=user.id,
        new_values=f"email={user.email}, name={name}",
    ))
    db.session.delete(user)
    db.session.commit()
    flash(f"User '{name}' deleted.", "success")
    return redirect(url_for("auth.user_list"))


# ── CREATE ROLE ──────────────────────────────────────────────────────
@auth_bp.route("/roles/create", methods=["POST"])
@login_required
def role_create():
    name = request.form.get("role_name", "").strip().lower()
    desc = request.form.get("role_description", "").strip()

    if not name:
        flash("Role name required.", "danger")
        return redirect(url_for("auth.user_list"))

    if Role.query.filter_by(name=name).first():
        flash(f"Role '{name}' already exists.", "warning")
        return redirect(url_for("auth.user_list"))

    db.session.add(Role(name=name, description=desc))
    db.session.commit()
    flash(f"Role '{name}' created.", "success")
    return redirect(url_for("auth.user_list"))


# ── DELETE ROLE ──────────────────────────────────────────────────────
@auth_bp.route("/roles/<int:role_id>/delete", methods=["POST"])
@login_required
def role_delete(role_id):
    role = db.session.get(Role, role_id)
    if not role:
        flash("Role not found.", "warning")
        return redirect(url_for("auth.user_list"))

    name = role.name
    db.session.delete(role)
    db.session.commit()
    flash(f"Role '{name}' deleted.", "success")
    return redirect(url_for("auth.user_list"))
