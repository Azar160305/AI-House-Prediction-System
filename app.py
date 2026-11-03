import os
import secrets
import json
import re
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, inspect, text
from dotenv import load_dotenv
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()
app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY") or secrets.token_hex(32)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///smart_house.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "0").lower() in {"1", "true", "yes"},
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
)
db = SQLAlchemy(app)


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    # `name` is retained for compatibility with existing databases and views.
    full_name = db.Column(db.String(150), nullable=True)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(25), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def display_name(self):
        return self.full_name or self.name

class HouseCategory(db.Model):
    __tablename__ = "house_categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    bedrooms = db.Column(db.Integer, default=0)
    bathrooms = db.Column(db.Integer, default=1)
    area = db.Column(db.Integer, default=800)
    base_cost = db.Column(db.Integer, default=2000000)
    description = db.Column(db.Text, default="")


class Prediction(db.Model):
    __tablename__ = "house_predictions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    inputs = db.Column(db.Text, nullable=False)
    result = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class LandReport(db.Model):
    __tablename__ = "land_details"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    details = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class WaterRecord(db.Model):
    __tablename__ = "water_level_records"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    level_m = db.Column(db.Float, nullable=False)
    borewell_depth_m = db.Column(db.Float)
    rainfall_mm = db.Column(db.Float)
    location = db.Column(db.String(160), default="")
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)


class SavedDesign(db.Model):
    __tablename__ = "saved_designs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("house_categories.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ChatMessage(db.Model):
    __tablename__ = "chat_history"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ConstructionRate(db.Model):
    __tablename__ = "construction_costs"
    id = db.Column(db.Integer, primary_key=True)
    region = db.Column(db.String(100), unique=True, nullable=False)
    rate_sqft = db.Column(db.Integer, nullable=False, default=2200)


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please sign in to continue.", "info")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapped


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            flash("Administrator access required.", "error")
            return redirect(url_for("dashboard"))
        return fn(*args, **kwargs)
    return wrapped


def current_user():
    uid = session.get("user_id")
    return db.session.get(User, uid) if uid else None


def upgrade_auth_schema():
    """Add auth profile columns in place, retaining all existing user rows."""
    db.create_all()
    inspector = inspect(db.engine)
    if not inspector.has_table("users"):
        return
    columns = {column["name"] for column in inspector.get_columns("users")}
    preparer = db.engine.dialect.identifier_preparer
    table_name = preparer.quote("users")
    if "full_name" not in columns:
        db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN full_name VARCHAR(150) NULL"))
    if "phone" not in columns:
        db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN phone VARCHAR(25) NULL"))
    if "name" in columns:
        name_column = preparer.quote("name")
        full_name_column = preparer.quote("full_name")
        db.session.execute(text(f"UPDATE {table_name} SET {full_name_column} = {name_column} WHERE {full_name_column} IS NULL OR {full_name_column} = ''"))
    db.session.commit()


@app.before_request
def ensure_schema_and_disable_page_cache():
    # create_all only creates missing tables; it never drops or replaces existing data.
    if not app.extensions.get("auth_schema_ready"):
        upgrade_auth_schema()
        app.extensions["auth_schema_ready"] = True


@app.after_request
def disable_authenticated_page_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def conceptual_floor_plan(bedrooms):
    """Return a simple illustrative room-block plan for the prediction result."""
    bedrooms = max(1, min(4, int(bedrooms)))
    # Coordinates are diagram coordinates, not construction dimensions.
    common = [
        {"name": "Living room", "x": 30, "y": 30, "w": 265, "h": 140, "size": "14 × 12 ft"},
        {"name": "Kitchen", "x": 295, "y": 30, "w": 245, "h": 95, "size": "10 × 9 ft"},
        {"name": "Dining", "x": 295, "y": 125, "w": 245, "h": 45, "size": "Shared space"},
        {"name": "Bathroom", "x": 430, "y": 170, "w": 110, "h": 80, "size": "5 × 7 ft"},
        {"name": "Bath / utility", "x": 430, "y": 250, "w": 110, "h": 90, "size": "Approx."},
    ]
    if bedrooms == 1:
        bedrooms_rooms = [
            {"name": "Bedroom 1", "x": 30, "y": 170, "w": 200, "h": 170, "size": "12 × 12 ft"},
            {"name": "Study / flex", "x": 230, "y": 170, "w": 200, "h": 170, "size": "Flexible use"},
        ]
    elif bedrooms == 2:
        bedrooms_rooms = [
            {"name": "Bedroom 1", "x": 30, "y": 170, "w": 200, "h": 170, "size": "12 × 12 ft"},
            {"name": "Bedroom 2", "x": 230, "y": 170, "w": 200, "h": 170, "size": "10 × 11 ft"},
        ]
    elif bedrooms == 3:
        common = [
            {"name": "Living room", "x": 30, "y": 30, "w": 265, "h": 140, "size": "14 × 12 ft"},
            {"name": "Kitchen", "x": 295, "y": 30, "w": 245, "h": 95, "size": "10 × 9 ft"},
            {"name": "Dining", "x": 295, "y": 125, "w": 245, "h": 45, "size": "Shared space"},
            {"name": "Bathroom", "x": 430, "y": 170, "w": 110, "h": 80, "size": "5 × 7 ft"},
            {"name": "Bath / utility", "x": 430, "y": 250, "w": 110, "h": 90, "size": "Approx."},
        ]
        bedrooms_rooms = [
            {"name": "Bedroom 1", "x": 30, "y": 170, "w": 200, "h": 170, "size": "12 × 12 ft"},
            {"name": "Bedroom 2", "x": 230, "y": 170, "w": 100, "h": 170, "size": "10 × 11 ft"},
            {"name": "Bedroom 3", "x": 330, "y": 170, "w": 100, "h": 170, "size": "10 × 10 ft"},
        ]
    else:
        common = [
            {"name": "Living room", "x": 30, "y": 30, "w": 265, "h": 140, "size": "14 × 12 ft"},
            {"name": "Kitchen", "x": 295, "y": 30, "w": 245, "h": 95, "size": "10 × 9 ft"},
            {"name": "Dining", "x": 295, "y": 125, "w": 245, "h": 45, "size": "Shared space"},
            {"name": "Bathroom", "x": 430, "y": 170, "w": 110, "h": 80, "size": "5 × 7 ft"},
            {"name": "Bath / utility", "x": 430, "y": 250, "w": 110, "h": 90, "size": "Approx."},
        ]
        bedrooms_rooms = [
            {"name": "Bedroom 1", "x": 30, "y": 170, "w": 150, "h": 170, "size": "12 × 12 ft"},
            {"name": "Bedroom 2", "x": 180, "y": 170, "w": 125, "h": 170, "size": "10 × 11 ft"},
            {"name": "Bedroom 3", "x": 305, "y": 170, "w": 125, "h": 80, "size": "10 × 10 ft"},
            {"name": "Bedroom 4", "x": 305, "y": 250, "w": 125, "h": 90, "size": "10 × 10 ft"},
        ]
    return common + bedrooms_rooms


@app.context_processor
def inject_user():
    return {"current_user": current_user(), "money": lambda n: f"₹{n:,.0f}"}


@app.route("/")
def home():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return render_template("home.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        errors = []
        if not full_name or len(full_name) > 100:
            errors.append("Enter your full name (up to 100 characters).")
        if len(email) > 160 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            errors.append("Enter a valid email address.")
        phone_digits = re.sub(r"\D", "", phone)
        if not phone or not 7 <= len(phone_digits) <= 15 or not re.fullmatch(r"\+?[0-9 ().-]+", phone):
            errors.append("Enter a valid phone number with 7 to 15 digits.")
        if len(password) < 8 or len(password) > 128:
            errors.append("Password must be 8 to 128 characters long.")
        if password != confirm_password:
            errors.append("Password and confirmation do not match.")
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("register.html", form=request.form)
        if User.query.filter(func.lower(User.email) == email).first():
            flash("An account with that email already exists.", "error")
            return render_template("register.html", form=request.form)
        user = User(
            name=full_name,
            full_name=full_name,
            email=email,
            phone=phone,
            password_hash=generate_password_hash(password),
        )
        try:
            db.session.add(user)
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash("We could not create the account. Check that the email is not already registered and try again.", "error")
            return render_template("register.html", form=request.form)
        flash("Registration complete. Sign in with your new account.", "success")
        return redirect(url_for("login"))
    return render_template("register.html", form={})


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter(func.lower(User.email) == email).first()
        if user and check_password_hash(user.password_hash, password):
            session.clear()
            session.permanent = False
            session["user_id"] = user.id
            session["is_admin"] = user.is_admin
            return redirect(url_for("admin" if user.is_admin else "dashboard"))
        flash("Email or password is incorrect.", "error")
    return render_template("login.html")


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        # Local development flow: show a one-time reset URL in the confirmation screen.
        user = User.query.filter_by(email=request.form.get("email", "").strip().lower()).first()
        if user:
            token = secrets.token_urlsafe(24)
            session["reset_token"] = token; session["reset_user"] = user.id
            flash("Local reset link: " + url_for("reset_password", token=token), "info")
        else:
            flash("If the account exists, reset instructions are ready.", "info")
        return redirect(url_for("forgot_password"))
    return render_template("auth.html", mode="forgot")


@app.route("/reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    if session.get("reset_token") != token:
        flash("That reset link is invalid or expired.", "error"); return redirect(url_for("forgot_password"))
    if request.method == "POST":
        password = request.form.get("password", "")
        if len(password) < 8:
            flash("Use at least 8 characters.", "error")
        else:
            user = db.session.get(User, session.pop("reset_user"))
            user.password_hash = generate_password_hash(password); db.session.commit()
            session.pop("reset_token", None); flash("Password updated. Sign in with your new password.", "success")
            return redirect(url_for("login"))
    return render_template("auth.html", mode="reset")


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    flash("You have logged out successfully.", "success")
    return redirect(url_for("login"))


@app.route("/profile")
@login_required
def profile():
    return render_template("profile.html", user=current_user())


@app.route("/dashboard")
@login_required
def dashboard():
    uid = session["user_id"]
    predictions = Prediction.query.filter_by(user_id=uid).order_by(Prediction.created_at.desc()).limit(5).all()
    saved_designs = db.session.query(HouseCategory).join(SavedDesign, SavedDesign.category_id == HouseCategory.id).filter(SavedDesign.user_id == uid).all()
    land_reports = LandReport.query.filter_by(user_id=uid).order_by(LandReport.created_at.desc()).limit(5).all()
    water_records = WaterRecord.query.filter_by(user_id=uid).order_by(WaterRecord.recorded_at.desc()).limit(5).all()
    return render_template(
        "dashboard.html",
        prediction_count=Prediction.query.filter_by(user_id=uid).count(),
        saved_count=len(saved_designs),
        land_count=LandReport.query.filter_by(user_id=uid).count(),
        water_count=WaterRecord.query.filter_by(user_id=uid).count(),
        predictions=predictions,
        saved_designs=saved_designs,
        land_reports=land_reports,
        water_records=water_records,
    )


@app.route("/houses")
def houses():
    return render_template("houses.html", categories=HouseCategory.query.order_by(HouseCategory.id).all(), saved_ids=[r.category_id for r in SavedDesign.query.filter_by(user_id=session.get("user_id")).all()] if session.get("user_id") else [])


@app.post("/houses/<int:category_id>/save")
@login_required
def save_design(category_id):
    if not HouseCategory.query.get_or_404(category_id): return redirect(url_for("houses"))
    existing = SavedDesign.query.filter_by(user_id=session["user_id"], category_id=category_id).first()
    if existing: db.session.delete(existing)
    else: db.session.add(SavedDesign(user_id=session["user_id"], category_id=category_id))
    db.session.commit(); return redirect(request.referrer or url_for("houses"))


@app.route("/prediction", methods=["GET", "POST"])
@login_required
def prediction():
    result = None
    if request.method == "POST":
        try:
            budget = float(request.form.get("budget", 0)); land_area = float(request.form.get("land_area", 0)); floors = max(1, int(request.form.get("floors", 1)))
            beds = max(1, int(request.form.get("bedrooms", 2))); baths = max(1, int(request.form.get("bathrooms", 1)))
            if budget <= 0 or land_area <= 0: raise ValueError
        except ValueError:
            flash("Enter positive budget and land area values.", "error")
        else:
            # Transparent rule-based prototype, not a trained model or a professional estimate.
            categories = HouseCategory.query.all()
            if not categories:
                flash("House categories are not set up yet. Run `flask --app app init-db` and try again.", "error")
            else:
                chosen = min(categories, key=lambda h: abs(h.bedrooms-beds) * 550000 + max(0, h.base_cost-budget) * 0.35 + max(0, h.area-land_area*0.72) * 1000)
                build_area = min(chosen.area, int(land_area * 0.72))
                rate = max(500, int(request.form.get("quality_rate", 2200)))
                estimate = build_area * rate * floors
                fit = max(20, min(98, round(100 - abs(chosen.area - land_area * .65) / max(land_area, 1) * 100)))
                result = {"name": chosen.name, "area": build_area, "cost": estimate, "duration": max(5, round(build_area*floors/250)), "fit": fit, "bedrooms": chosen.bedrooms, "floors": floors, "rooms": conceptual_floor_plan(chosen.bedrooms)}
                # Text columns need serialized JSON, not a Python dict (otherwise POST fails at commit).
                db.session.add(Prediction(user_id=session["user_id"], inputs=json.dumps(request.form.to_dict()), result=json.dumps(result)))
                db.session.commit()
    return render_template("prediction.html", result=result, categories=HouseCategory.query.all())


@app.route("/land", methods=["GET", "POST"])
@login_required
def land():
    report = None
    if request.method == "POST":
        try:
            area = float(request.form.get("area", 0)); length = float(request.form.get("length", 0)); width = float(request.form.get("width", 0))
            if area <= 0: raise ValueError
        except ValueError: flash("Enter a valid land area.", "error")
        else:
            report = {"area": area, "dimensions": f"{length:g} × {width:g} ft" if length and width else "Not supplied", "fit": min(96, max(30, round(55 + min(area, 3000)/100))), "house": "2BHK or compact 3BHK" if area < 1800 else "3BHK or villa", "note": "Preliminary software estimate; verify site dimensions, setbacks, soil and local planning rules with qualified professionals."}
            db.session.add(LandReport(user_id=session["user_id"], details=__import__("json").dumps({"inputs": request.form.to_dict(), "result": report}))); db.session.commit()
    return render_template("land.html", report=report)


@app.route("/water", methods=["GET", "POST"])
@login_required
def water():
    if request.method == "POST":
        try:
            level = float(request.form.get("level", "")); depth = float(request.form.get("depth", 0) or 0); rain = float(request.form.get("rainfall", 0) or 0)
            if level < 0 or depth < 0 or rain < 0: raise ValueError
        except ValueError: flash("Enter non-negative numeric readings.", "error")
        else:
            db.session.add(WaterRecord(user_id=session["user_id"], level_m=level, borewell_depth_m=depth, rainfall_mm=rain, location=request.form.get("location", ""))); db.session.commit()
            flash("Water reading saved. The recorded value is user-entered, not independently verified.", "success")
            return redirect(url_for("water"))
    records = WaterRecord.query.filter_by(user_id=session["user_id"]).order_by(WaterRecord.recorded_at.desc()).limit(12).all()
    records.reverse()
    return render_template("water.html", records=records)


@app.route("/assistant", methods=["GET", "POST"])
@login_required
def assistant():
    answer = None
    if request.method == "POST":
        q = request.form.get("question", "").strip()
        if q:
            lower = q.lower()
            if "water" in lower or "storage" in lower: answer = "For a starting point, plan around 135 litres per person per day and store at least one to two days of household demand. Local codes, climate and supply reliability change the right capacity. This is general guidance, not a site assessment."
            elif "soil" in lower or "foundation" in lower: answer = "Foundation choice depends on a geotechnical investigation, groundwater and the building loads. Arrange a site-specific soil test and have a licensed structural professional select the foundation."
            elif "cost" in lower or "budget" in lower: answer = "Use the prediction tool to compare a transparent area × rate estimate. Rates vary by location, specification and date; treat the result as an early planning estimate and get local quotations."
            elif "1200" in lower or "3bhk" in lower: answer = "A 3BHK may fit on 1,200 sq.ft of land, but usable built-up area depends on setbacks, plot shape, parking, local rules and floor count. Check the land analysis and confirm with a local architect."
            else: answer = "I can help with early planning. Share your budget, usable land area, location, floors and family size; recommendations here are simulated and should be checked by local professionals."
            db.session.add(ChatMessage(user_id=session["user_id"], question=q, answer=answer)); db.session.commit()
    history = ChatMessage.query.filter_by(user_id=session["user_id"]).order_by(ChatMessage.created_at.desc()).limit(8).all()
    return render_template("assistant.html", answer=answer, history=history)


@app.route("/admin")
@login_required
@admin_required
def admin():
    return render_template("admin.html", users=User.query.order_by(User.created_at.desc()).all(), categories=HouseCategory.query.all(), rates=ConstructionRate.query.all(), prediction_count=Prediction.query.count())


@app.post("/admin/category")
@login_required
@admin_required
def add_category():
    try:
        db.session.add(HouseCategory(name=request.form["name"].strip(), bedrooms=int(request.form.get("bedrooms", 0)), bathrooms=int(request.form.get("bathrooms", 1)), area=int(request.form.get("area", 800)), base_cost=int(request.form.get("cost", 2000000))))
        db.session.commit(); flash("House category added.", "success")
    except Exception:
        db.session.rollback(); flash("Could not add category. Check the values and ensure its name is unique.", "error")
    return redirect(url_for("admin"))


@app.post("/admin/category/<int:category_id>/update")
@login_required
@admin_required
def update_category(category_id):
    category = HouseCategory.query.get_or_404(category_id)
    try:
        category.name = request.form["name"].strip()
        category.bedrooms = int(request.form.get("bedrooms", 0))
        category.bathrooms = int(request.form.get("bathrooms", 1))
        category.area = int(request.form.get("area", 800))
        category.base_cost = int(request.form.get("cost", 2000000))
        if not category.name or min(category.bathrooms, category.area, category.base_cost) <= 0 or category.bedrooms < 0:
            raise ValueError
        db.session.commit(); flash("House category updated.", "success")
    except Exception:
        db.session.rollback(); flash("Could not update category. Check values and ensure the name is unique.", "error")
    return redirect(url_for("admin"))


@app.post("/admin/category/<int:category_id>/delete")
@login_required
@admin_required
def delete_category(category_id):
    category = HouseCategory.query.get_or_404(category_id)
    if SavedDesign.query.filter_by(category_id=category.id).first():
        flash("This category has saved designs and cannot be removed yet.", "error")
    else:
        db.session.delete(category); db.session.commit(); flash("House category deleted.", "success")
    return redirect(url_for("admin"))


@app.post("/admin/rate")
@login_required
@admin_required
def set_rate():
    region = request.form.get("region", "").strip()
    try:
        rate = int(request.form.get("rate", 0))
        if not region or rate <= 0: raise ValueError
        row = ConstructionRate.query.filter_by(region=region).first()
        if row: row.rate_sqft = rate
        else: db.session.add(ConstructionRate(region=region, rate_sqft=rate))
        db.session.commit(); flash("Regional rate saved.", "success")
    except ValueError: flash("Enter a region and a positive per-square-foot rate.", "error")
    return redirect(url_for("admin"))


@app.cli.command("init-db")
def init_db():
    upgrade_auth_schema()
    if not HouseCategory.query.first():
        samples = [("1BHK House",1,1,550,1400000),("2BHK House",2,2,900,2300000),("3BHK House",3,2,1350,3500000),("4BHK House",4,3,1900,5100000),("Individual Villa",3,3,1800,6000000),("Duplex House",4,3,2100,6500000),("Independent House",3,2,1450,3900000),("Apartment",2,2,1000,2600000)]
        for name,beds,baths,area,cost in samples:
            db.session.add(HouseCategory(name=name,bedrooms=beds,bathrooms=baths,area=area,base_cost=cost,description="Illustrative planning profile. Confirm specifications with a local professional."))
    if not User.query.filter_by(email="admin@smarthouse.local").first():
        db.session.add(User(name="Demo Admin",full_name="Demo Admin",email="admin@smarthouse.local",phone="",password_hash=generate_password_hash(os.getenv("ADMIN_PASSWORD","Admin123!")),is_admin=True))
    db.session.commit()
    print("Database ready. Admin login: admin@smarthouse.local / Admin123! (change ADMIN_PASSWORD for setup).")


@app.cli.command("upgrade-auth-schema")
def upgrade_auth_schema_command():
    """Safely add auth profile fields and retain existing account rows."""
    upgrade_auth_schema()
    print("Authentication schema is up to date. Existing users and project records were retained.")


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )
